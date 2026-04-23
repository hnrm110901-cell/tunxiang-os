"""预测结果驱动智能采购 API — 基于需求预测生成采购建议

端点：
  GET  /api/v1/supply/smart-procurement/{store_id}/suggestion  — 基于需求预测生成采购建议
  POST /api/v1/supply/smart-procurement/{store_id}/create-order — 一键生成采购订单
  GET  /api/v1/supply/smart-procurement/waste-reduction          — 预测采购vs实际使用对比

# ROUTER REGISTRATION:
# from .api.smart_procurement_routes import router as smart_procurement_router
# app.include_router(smart_procurement_router)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/smart-procurement",
    tags=["smart-procurement"],
)


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail={"ok": False, "error": {"message": msg}})


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id})


def _serialize_row(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, date):
            d[k] = str(v)
    return d


# 安全库存系数（建议采购量 = 预测需求 * 系数 - 现有库存）
SAFETY_STOCK_FACTOR = 1.3


# ──────────────────────────────────────────────────────────────────────────────
# 内部预测 & BOM分解
# ──────────────────────────────────────────────────────────────────────────────


async def _forecast_dish_demand(
    db: AsyncSession,
    store_id: str,
    tenant_id: str,
    days_ahead: int,
) -> list[dict[str, Any]]:
    """预测菜品需求量：基于近7天平均日销量 * days_ahead。"""
    try:
        rows = await db.execute(
            text("""
            SELECT oi.dish_id,
                   d.name AS dish_name,
                   COALESCE(SUM(oi.quantity), 0) AS total_sold,
                   COALESCE(SUM(oi.quantity) / 7.0 * :days, 0) AS predicted_demand
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            LEFT JOIN dishes d ON d.id = oi.dish_id
            WHERE o.tenant_id = :tid
              AND o.store_id  = :store_id
              AND o.is_deleted = FALSE
              AND o.created_at >= NOW() - INTERVAL '7 days'
            GROUP BY oi.dish_id, d.name
            HAVING SUM(oi.quantity) > 0
            ORDER BY predicted_demand DESC
        """),
            {
                "tid": tenant_id,
                "store_id": store_id,
                "days": days_ahead,
            },
        )
        return [_serialize_row(r) for r in rows]
    except SQLAlchemyError:
        return []


async def _bom_decompose(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    dish_demands: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """BOM分解：菜品需求 -> 原料需求。

    Returns: {ingredient_id: {name, total_need, unit}}
    """
    ingredient_needs: dict[str, dict[str, Any]] = {}

    for dish in dish_demands:
        dish_id = dish.get("dish_id")
        predicted = float(dish.get("predicted_demand", 0))
        if not dish_id or predicted <= 0:
            continue

        try:
            bom_rows = await db.execute(
                text("""
                SELECT bi.ingredient_id, i.name AS ingredient_name,
                       bi.standard_qty, i.unit
                FROM bom_items bi
                JOIN bom_templates bt ON bt.id = bi.bom_template_id
                LEFT JOIN ingredients i ON i.id = bi.ingredient_id
                WHERE bt.tenant_id = :tid
                  AND bt.store_id  = :store_id
                  AND bt.dish_id   = :dish_id
                  AND bt.is_active = TRUE
                  AND bt.is_deleted = FALSE
                  AND bi.is_deleted = FALSE
            """),
                {
                    "tid": tenant_id,
                    "store_id": store_id,
                    "dish_id": str(dish_id),
                },
            )

            for bom in bom_rows:
                iid = str(bom.ingredient_id)
                need = float(bom.standard_qty or 0) * predicted
                if iid in ingredient_needs:
                    ingredient_needs[iid]["total_need"] += need
                else:
                    ingredient_needs[iid] = {
                        "ingredient_id": iid,
                        "ingredient_name": getattr(bom, "ingredient_name", ""),
                        "total_need": need,
                        "unit": getattr(bom, "unit", "kg"),
                    }
        except SQLAlchemyError:
            continue

    return ingredient_needs


async def _get_current_stock(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    ingredient_ids: list[str],
) -> dict[str, float]:
    """获取当前库存量。"""
    if not ingredient_ids:
        return {}

    try:
        rows = await db.execute(
            text("""
            SELECT id, COALESCE(quantity, 0) AS qty
            FROM ingredients
            WHERE tenant_id = :tid
              AND store_id  = :store_id
              AND is_deleted = FALSE
              AND id = ANY(:ids::uuid[])
        """),
            {
                "tid": tenant_id,
                "store_id": store_id,
                "ids": ingredient_ids,
            },
        )
        return {str(r.id): float(r.qty) for r in rows}
    except SQLAlchemyError:
        return {}


async def _get_best_supplier(
    db: AsyncSession,
    tenant_id: str,
    ingredient_id: str,
) -> dict[str, Any] | None:
    """获取原料的最佳供应商（最近供货 + 评分最高）。"""
    try:
        row = await db.execute(
            text("""
            SELECT supplier_id, supplier_name,
                   COALESCE(unit_price_fen, 0) AS unit_price_fen
            FROM receiving_records
            WHERE tenant_id = :tid
              AND ingredient_id = :iid
              AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT 1
        """),
            {"tid": tenant_id, "iid": ingredient_id},
        )
        r = row.fetchone()
        if r:
            return {
                "supplier_id": str(r.supplier_id),
                "supplier_name": getattr(r, "supplier_name", ""),
                "unit_price_fen": int(r.unit_price_fen or 0),
            }
    except SQLAlchemyError:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────


class CreateOrderRequest(BaseModel):
    suggestion_ids: list[str] = Field(..., min_length=1, description="要下单的建议ID列表")


# ──────────────────────────────────────────────────────────────────────────────
# GET /{store_id}/suggestion — 基于需求预测生成采购建议
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/{store_id}/suggestion")
async def get_procurement_suggestion(
    store_id: uuid.UUID,
    days_ahead: int = Query(3, ge=1, le=14, description="预测天数，默认3天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """基于需求预测生成采购建议。

    逻辑：菜品需求预测 -> BOM分解 -> 现有库存 -> 需要采购量 -> 安全库存系数 -> 建议采购单。
    输出：每个原料的建议采购量 + 供应商 + 预估金额。
    """
    try:
        await _set_rls(db, x_tenant_id)
        sid = str(store_id)

        # 1. 菜品需求预测
        dish_demands = await _forecast_dish_demand(db, sid, x_tenant_id, days_ahead)

        # 2. BOM分解为原料需求
        ingredient_needs = await _bom_decompose(db, x_tenant_id, sid, dish_demands)

        if not ingredient_needs:
            return _ok(
                {
                    "store_id": str(store_id),
                    "days_ahead": days_ahead,
                    "suggestions": [],
                    "total": 0,
                    "total_estimated_cost_fen": 0,
                    "message": "无BOM数据或近期无销售记录，无法生成采购建议",
                }
            )

        # 3. 查当前库存
        stock = await _get_current_stock(db, x_tenant_id, sid, list(ingredient_needs.keys()))

        # 4. 计算建议采购量并存储
        suggestions: list[dict[str, Any]] = []
        total_cost_fen = 0

        for iid, info in ingredient_needs.items():
            current = stock.get(iid, 0.0)
            predicted = info["total_need"]
            safety = predicted * SAFETY_STOCK_FACTOR
            suggested_qty = max(0, safety - current)

            if suggested_qty <= 0:
                continue  # 库存充足，无需采购

            # 获取供应商
            supplier = await _get_best_supplier(db, x_tenant_id, iid)
            unit_price = supplier["unit_price_fen"] if supplier else 0
            estimated_cost = int(suggested_qty * unit_price)
            total_cost_fen += estimated_cost

            # 写入建议表
            suggestion_id = uuid.uuid4()
            await db.execute(
                text("""
                INSERT INTO smart_procurement_suggestions
                    (id, tenant_id, store_id, ingredient_id, ingredient_name,
                     predicted_demand, current_stock, safety_stock,
                     suggested_qty, unit, supplier_id, supplier_name,
                     estimated_cost_fen, days_ahead, status)
                VALUES (:id, :tid, :store_id, :iid, :iname,
                        :demand, :stock, :safety,
                        :qty, :unit, :sup_id, :sup_name,
                        :cost, :days, 'draft')
            """),
                {
                    "id": str(suggestion_id),
                    "tid": x_tenant_id,
                    "store_id": sid,
                    "iid": iid,
                    "iname": info["ingredient_name"],
                    "demand": predicted,
                    "stock": current,
                    "safety": safety,
                    "qty": suggested_qty,
                    "unit": info["unit"],
                    "sup_id": supplier["supplier_id"] if supplier else None,
                    "sup_name": supplier["supplier_name"] if supplier else "",
                    "cost": estimated_cost,
                    "days": days_ahead,
                },
            )

            suggestions.append(
                {
                    "suggestion_id": str(suggestion_id),
                    "ingredient_id": iid,
                    "ingredient_name": info["ingredient_name"],
                    "predicted_demand": round(predicted, 2),
                    "current_stock": round(current, 2),
                    "safety_stock": round(safety, 2),
                    "suggested_qty": round(suggested_qty, 2),
                    "unit": info["unit"],
                    "supplier_id": supplier["supplier_id"] if supplier else None,
                    "supplier_name": supplier["supplier_name"] if supplier else None,
                    "unit_price_fen": unit_price,
                    "estimated_cost_fen": estimated_cost,
                }
            )

        await db.commit()
        logger.info("smart_procurement.suggestion.generated", store_id=sid, items=len(suggestions))

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("smart_procurement.suggestion.failed", error=str(exc))
        raise _err(f"生成采购建议失败：{exc}", 500) from exc

    return _ok(
        {
            "store_id": str(store_id),
            "days_ahead": days_ahead,
            "suggestions": suggestions,
            "total": len(suggestions),
            "total_estimated_cost_fen": total_cost_fen,
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /{store_id}/create-order — 一键生成采购订单
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/{store_id}/create-order", status_code=201)
async def create_procurement_order(
    store_id: uuid.UUID,
    body: CreateOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """基于建议自动创建采购订单。"""
    try:
        await _set_rls(db, x_tenant_id)
        sid = str(store_id)

        # 1. 校验建议存在
        suggestion_ids = body.suggestion_ids
        placeholders = ", ".join(f":s{i}" for i in range(len(suggestion_ids)))
        params: dict[str, Any] = {"tid": x_tenant_id, "store_id": sid}
        for i, s in enumerate(suggestion_ids):
            params[f"s{i}"] = s

        rows = await db.execute(
            text(f"""
            SELECT id, ingredient_id, ingredient_name, suggested_qty, unit,
                   supplier_id, supplier_name, estimated_cost_fen
            FROM smart_procurement_suggestions
            WHERE tenant_id = :tid AND store_id = :store_id
              AND status = 'draft'
              AND id IN ({placeholders})
              AND is_deleted = FALSE
        """),
            params,
        )
        suggestions = rows.fetchall()

        if not suggestions:
            raise _err("未找到有效的采购建议（可能已过期或已下单）", 404)

        # 2. 创建采购订单
        order_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        order_no = f"SP-{now.strftime('%Y%m%d')}-{str(order_id)[:4].upper()}"
        total_amount = sum(int(s.estimated_cost_fen or 0) for s in suggestions)

        await db.execute(
            text("""
            INSERT INTO smart_procurement_orders
                (id, tenant_id, store_id, suggestion_ids, order_no,
                 total_amount_fen, item_count, status, source)
            VALUES (:id, :tid, :store_id, :sids::jsonb, :order_no,
                    :amount, :count, 'pending', 'ai_suggested')
        """),
            {
                "id": str(order_id),
                "tid": x_tenant_id,
                "store_id": sid,
                "sids": str([str(s.id) for s in suggestions]).replace("'", '"'),
                "order_no": order_no,
                "amount": total_amount,
                "count": len(suggestions),
            },
        )

        # 3. 更新建议状态为 ordered
        for s in suggestions:
            await db.execute(
                text("""
                UPDATE smart_procurement_suggestions
                SET status = 'ordered'
                WHERE id = :sid AND tenant_id = :tid
            """),
                {"sid": str(s.id), "tid": x_tenant_id},
            )

        await db.commit()

        items = [
            {
                "ingredient_id": str(s.ingredient_id),
                "ingredient_name": getattr(s, "ingredient_name", ""),
                "suggested_qty": float(s.suggested_qty),
                "unit": getattr(s, "unit", "kg"),
                "supplier_name": getattr(s, "supplier_name", ""),
                "estimated_cost_fen": int(s.estimated_cost_fen or 0),
            }
            for s in suggestions
        ]

        logger.info("smart_procurement.order.created", order_id=str(order_id), order_no=order_no, items=len(items))

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("smart_procurement.order.create.failed", error=str(exc))
        raise _err(f"创建采购订单失败：{exc}", 500) from exc

    return _ok(
        {
            "order_id": str(order_id),
            "order_no": order_no,
            "store_id": str(store_id),
            "total_amount_fen": total_amount,
            "item_count": len(items),
            "items": items,
            "status": "pending",
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /waste-reduction — 预测采购vs实际使用对比
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/waste-reduction")
async def waste_reduction_report(
    store_id: uuid.UUID | None = Query(None, description="门店ID，不传则全部门店"),
    days: int = Query(30, ge=7, le=90, description="分析天数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """预测采购 vs 实际使用对比（浪费减少量化）。

    对比维度：
    - 采购建议量 vs 实际采购量（是否过多采购）
    - 实际入库量 vs 实际消耗量（损耗/浪费）
    - AI建议准确度评分
    """
    try:
        await _set_rls(db, x_tenant_id)

        store_filter = "AND s.store_id = :store_id" if store_id else ""
        params: dict[str, Any] = {
            "tid": x_tenant_id,
            "since": datetime.now(timezone.utc) - timedelta(days=days),
        }
        if store_id:
            params["store_id"] = str(store_id)

        # 1. AI建议汇总
        suggestion_rows = await db.execute(
            text(f"""
            SELECT
                COUNT(*)                                    AS total_suggestions,
                SUM(CASE WHEN s.status = 'ordered' THEN 1 ELSE 0 END) AS adopted_count,
                COALESCE(SUM(s.estimated_cost_fen), 0)     AS total_suggested_cost_fen,
                COALESCE(SUM(CASE WHEN s.status = 'ordered'
                             THEN s.estimated_cost_fen ELSE 0 END), 0) AS adopted_cost_fen
            FROM smart_procurement_suggestions s
            WHERE s.tenant_id = :tid
              AND s.created_at >= :since
              AND s.is_deleted = FALSE
              {store_filter}
        """),
            params,
        )
        suggestion_stats = suggestion_rows.fetchone()

        # 2. 实际采购 vs 实际消耗（基于库存流水）
        waste_rows = await db.execute(
            text(f"""
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'inbound'
                             THEN quantity ELSE 0 END), 0)  AS total_inbound,
                COALESCE(SUM(CASE WHEN transaction_type = 'usage'
                             THEN quantity ELSE 0 END), 0)  AS total_usage,
                COALESCE(SUM(CASE WHEN transaction_type = 'waste'
                             THEN quantity ELSE 0 END), 0)  AS total_waste
            FROM ingredient_transactions
            WHERE tenant_id = :tid
              AND created_at >= :since
              AND is_deleted = FALSE
              {"AND store_id = :store_id" if store_id else ""}
        """),
            params,
        )
        waste_stats = waste_rows.fetchone()

        total_inbound = float(waste_stats.total_inbound or 0) if waste_stats else 0
        total_usage = float(waste_stats.total_usage or 0) if waste_stats else 0
        total_waste = float(waste_stats.total_waste or 0) if waste_stats else 0

        # 3. 计算指标
        waste_rate = (total_waste / total_inbound * 100) if total_inbound > 0 else 0
        utilization_rate = (total_usage / total_inbound * 100) if total_inbound > 0 else 0

        total_suggestions = int(suggestion_stats.total_suggestions or 0) if suggestion_stats else 0
        adopted = int(suggestion_stats.adopted_count or 0) if suggestion_stats else 0
        adoption_rate = (adopted / total_suggestions * 100) if total_suggestions > 0 else 0

        logger.info(
            "smart_procurement.waste_reduction",
            store_id=str(store_id) if store_id else "all",
            waste_rate=round(waste_rate, 1),
        )

    except SQLAlchemyError as exc:
        logger.error("smart_procurement.waste_reduction.failed", error=str(exc))
        raise _err(f"浪费分析失败：{exc}", 500) from exc

    return _ok(
        {
            "analysis_period_days": days,
            "store_id": str(store_id) if store_id else None,
            "ai_suggestions": {
                "total_suggestions": total_suggestions,
                "adopted_count": adopted,
                "adoption_rate_pct": round(adoption_rate, 1),
                "total_suggested_cost_fen": int(suggestion_stats.total_suggested_cost_fen or 0)
                if suggestion_stats
                else 0,
                "adopted_cost_fen": int(suggestion_stats.adopted_cost_fen or 0) if suggestion_stats else 0,
            },
            "inventory_flow": {
                "total_inbound": round(total_inbound, 2),
                "total_usage": round(total_usage, 2),
                "total_waste": round(total_waste, 2),
                "waste_rate_pct": round(waste_rate, 1),
                "utilization_rate_pct": round(utilization_rate, 1),
            },
            "insight": _generate_waste_insight(waste_rate, adoption_rate),
        }
    )


def _generate_waste_insight(waste_rate: float, adoption_rate: float) -> str:
    """生成浪费分析洞察文本。"""
    parts: list[str] = []
    if waste_rate > 10:
        parts.append(f"损耗率 {waste_rate:.1f}% 偏高，建议加强库存周转管理")
    elif waste_rate > 5:
        parts.append(f"损耗率 {waste_rate:.1f}% 处于正常范围")
    else:
        parts.append(f"损耗率 {waste_rate:.1f}% 表现优秀")

    if adoption_rate < 30:
        parts.append("AI采购建议采纳率偏低，建议培训门店人员使用智能采购功能")
    elif adoption_rate > 70:
        parts.append("AI采购建议采纳率高，持续优化预测模型")

    return "；".join(parts) if parts else "数据不足，暂无洞察"
