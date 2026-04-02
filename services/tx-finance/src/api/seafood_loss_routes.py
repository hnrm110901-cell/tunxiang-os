"""活鲜损耗核算 API 路由

端点：
  POST /api/v1/finance/seafood-loss/record   — 录入活鲜死亡损耗
  GET  /api/v1/finance/seafood-loss          — 查询损耗记录（?store_id=&date=）
  GET  /api/v1/finance/seafood-loss/analysis — 损耗趋势分析（?store_id=&days=）
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-seafood-loss"])


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class RecordSeafoodLossRequest(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    loss_date: str = Field(..., description="损耗日期 YYYY-MM-DD")
    dish_id: str = Field(..., description="活鲜菜品ID（UUID）")
    description: str = Field(..., max_length=200, description="损耗描述（如：大黄鱼自然死亡3条）")
    amount_fen: int = Field(..., ge=0, description="损耗成本（分）")
    quantity: float = Field(..., gt=0, description="数量（kg 或 条/头）")
    unit: str = Field(..., description="单位（kg/g/jin/liang/条/头）")
    unit_cost_fen: Optional[int] = Field(None, ge=0, description="单位采购成本（分）")
    tank_zone_id: Optional[str] = Field(None, description="鱼缸区域ID（UUID，可选）")
    notes: Optional[str] = Field(None, max_length=500, description="备注")

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        allowed = {"kg", "g", "jin", "liang", "条", "头", "只", "个"}
        if v not in allowed:
            raise ValueError(f"unit 必须为以下之一: {', '.join(sorted(allowed))}")
        return v


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD"
        ) from exc


# ─── POST /seafood-loss/record — 录入活鲜死亡损耗 ────────────────────────────

@router.post("/seafood-loss/record", summary="录入活鲜死亡损耗")
async def record_seafood_loss(
    body: RecordSeafoodLossRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    录入当日活鲜死亡损耗记录。

    同时写入 cost_items 表（cost_type=live_seafood_death），
    供日 P&L 计算引擎直接使用，无需重新聚合 live_seafood_weigh_records。

    适用场景：
    - 每日开档前盘点死亡活鲜
    - 运输途中活鲜死亡
    - 活鲜池水质事故批量死亡

    返回新建的 cost_items 记录 ID。
    """
    sid = _parse_uuid(body.store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    dish_id = _parse_uuid(body.dish_id, "dish_id")
    loss_date = _parse_date_param(body.loss_date)

    tank_zone_id_str: Optional[str] = None
    if body.tank_zone_id:
        tank_zone_id = _parse_uuid(body.tank_zone_id, "tank_zone_id")
        tank_zone_id_str = str(tank_zone_id)

    # 写入 cost_items 表
    result = await db.execute(
        text("""
            INSERT INTO cost_items
            (tenant_id, store_id, cost_date, cost_type, reference_id,
             description, amount_fen, quantity, unit, unit_cost_fen)
            VALUES
            (:tenant_id::UUID, :store_id::UUID, :cost_date,
             'live_seafood_death',
             :dish_id::UUID,
             :description, :amount_fen, :quantity, :unit, :unit_cost_fen)
            RETURNING id
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": loss_date.isoformat(),
            "dish_id": str(dish_id),
            "description": body.description,
            "amount_fen": body.amount_fen,
            "quantity": body.quantity,
            "unit": body.unit,
            "unit_cost_fen": body.unit_cost_fen,
        },
    )
    cost_item_id = result.scalar_one()
    await db.commit()

    logger.info(
        "seafood_loss.recorded",
        tenant_id=str(tid),
        store_id=str(sid),
        dish_id=str(dish_id),
        amount_fen=body.amount_fen,
        quantity=body.quantity,
        unit=body.unit,
    )

    return {
        "ok": True,
        "data": {
            "cost_item_id": str(cost_item_id),
            "store_id": body.store_id,
            "loss_date": str(loss_date),
            "dish_id": body.dish_id,
            "description": body.description,
            "amount_fen": body.amount_fen,
            "quantity": body.quantity,
            "unit": body.unit,
        },
    }


# ─── GET /seafood-loss — 查询损耗记录 ────────────────────────────────────────

@router.get("/seafood-loss", summary="查询活鲜损耗记录")
async def get_seafood_loss_records(
    store_id: str = Query(..., description="门店ID"),
    loss_date: str = Query("today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店指定日期的活鲜损耗记录列表。

    从 cost_items 表查询 cost_type=live_seafood_death 的记录，
    并关联菜品名称。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(loss_date)

    offset = (page - 1) * size

    count_result = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM cost_items
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND cost_date = :cost_date
              AND cost_type = 'live_seafood_death'
              AND is_deleted = FALSE
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": biz_date.isoformat(),
        },
    )
    total = count_result.scalar()

    items_result = await db.execute(
        text("""
            SELECT
                ci.id,
                ci.cost_date,
                ci.description,
                ci.amount_fen,
                ci.quantity,
                ci.unit,
                ci.unit_cost_fen,
                ci.reference_id,
                ci.created_at,
                d.name AS dish_name
            FROM cost_items ci
            LEFT JOIN dishes d ON d.id = ci.reference_id AND d.is_deleted = FALSE
            WHERE ci.tenant_id = :tenant_id::UUID
              AND ci.store_id = :store_id::UUID
              AND ci.cost_date = :cost_date
              AND ci.cost_type = 'live_seafood_death'
              AND ci.is_deleted = FALSE
            ORDER BY ci.created_at DESC
            LIMIT :size OFFSET :offset
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "cost_date": biz_date.isoformat(),
            "size": size,
            "offset": offset,
        },
    )
    rows = items_result.fetchall()

    items = [
        {
            "id": str(r[0]),
            "cost_date": str(r[1]),
            "description": r[2],
            "amount_fen": r[3],
            "quantity": float(r[4]) if r[4] is not None else None,
            "unit": r[5],
            "unit_cost_fen": r[6],
            "dish_id": str(r[7]) if r[7] else None,
            "dish_name": r[9],
            "created_at": str(r[8]),
        }
        for r in rows
    ]

    daily_total = sum(item["amount_fen"] for item in items)

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date": str(biz_date),
            "daily_loss_fen": daily_total,
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ─── GET /seafood-loss/analysis — 损耗趋势分析 ───────────────────────────────

@router.get("/seafood-loss/analysis", summary="活鲜损耗趋势分析")
async def get_seafood_loss_analysis(
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(30, ge=7, le=90, description="查询天数（默认30天）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    活鲜损耗趋势分析（最近 N 天）。

    返回：
    - 每日损耗金额趋势
    - 各菜品损耗排名 TOP10（哪种活鲜损耗最高）
    - 损耗占食材成本比率趋势
    - 周均损耗金额
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    # 每日损耗趋势
    daily_result = await db.execute(
        text("""
            SELECT
                ci.cost_date,
                SUM(ci.amount_fen) AS loss_fen,
                COUNT(*) AS record_count
            FROM cost_items ci
            WHERE ci.tenant_id = :tenant_id::UUID
              AND ci.store_id = :store_id::UUID
              AND ci.cost_date BETWEEN :start_date AND :end_date
              AND ci.cost_type = 'live_seafood_death'
              AND ci.is_deleted = FALSE
            GROUP BY ci.cost_date
            ORDER BY ci.cost_date ASC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    daily_rows = daily_result.fetchall()

    daily_trend = [
        {
            "date": str(r[0]),
            "loss_fen": int(r[1]),
            "record_count": int(r[2]),
        }
        for r in daily_rows
    ]

    # 菜品损耗 TOP10
    dish_result = await db.execute(
        text("""
            SELECT
                ci.reference_id AS dish_id,
                COALESCE(d.name, '未知菜品') AS dish_name,
                SUM(ci.amount_fen) AS total_loss_fen,
                SUM(ci.quantity) AS total_qty,
                ci.unit,
                COUNT(*) AS record_count
            FROM cost_items ci
            LEFT JOIN dishes d ON d.id = ci.reference_id AND d.is_deleted = FALSE
            WHERE ci.tenant_id = :tenant_id::UUID
              AND ci.store_id = :store_id::UUID
              AND ci.cost_date BETWEEN :start_date AND :end_date
              AND ci.cost_type = 'live_seafood_death'
              AND ci.is_deleted = FALSE
            GROUP BY ci.reference_id, d.name, ci.unit
            ORDER BY total_loss_fen DESC
            LIMIT 10
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    dish_rows = dish_result.fetchall()

    total_period_loss = sum(int(r[2]) for r in dish_rows)
    top_dishes = [
        {
            "dish_id": str(r[0]) if r[0] else None,
            "dish_name": r[1],
            "total_loss_fen": int(r[2]),
            "total_qty": float(r[3]) if r[3] is not None else 0.0,
            "unit": r[4],
            "record_count": int(r[5]),
            "ratio": round(int(r[2]) / total_period_loss, 4) if total_period_loss > 0 else 0.0,
        }
        for r in dish_rows
    ]

    # 损耗占食材成本比率（从 daily_pnl 表关联）
    ratio_result = await db.execute(
        text("""
            SELECT
                dp.pnl_date,
                dp.food_cost_fen,
                COALESCE(ci_agg.loss_fen, 0) AS loss_fen
            FROM daily_pnl dp
            LEFT JOIN (
                SELECT cost_date, SUM(amount_fen) AS loss_fen
                FROM cost_items
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND cost_date BETWEEN :start_date AND :end_date
                  AND cost_type = 'live_seafood_death'
                  AND is_deleted = FALSE
                GROUP BY cost_date
            ) ci_agg ON ci_agg.cost_date = dp.pnl_date
            WHERE dp.tenant_id = :tenant_id::UUID
              AND dp.store_id = :store_id::UUID
              AND dp.pnl_date BETWEEN :start_date AND :end_date
              AND dp.is_deleted = FALSE
            ORDER BY dp.pnl_date ASC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    ratio_rows = ratio_result.fetchall()
    loss_ratio_trend = [
        {
            "date": str(r[0]),
            "food_cost_fen": int(r[1]),
            "seafood_loss_fen": int(r[2]),
            "loss_ratio": round(int(r[2]) / int(r[1]), 4) if int(r[1]) > 0 else 0.0,
        }
        for r in ratio_rows
    ]

    # 汇总统计
    total_loss = sum(d["loss_fen"] for d in daily_trend)
    days_with_loss = len([d for d in daily_trend if d["loss_fen"] > 0])
    avg_daily_loss = total_loss // days if days > 0 else 0

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "days": days,
            "summary": {
                "total_loss_fen": total_loss,
                "days_with_loss": days_with_loss,
                "avg_daily_loss_fen": avg_daily_loss,
                "top_loss_dish": top_dishes[0]["dish_name"] if top_dishes else None,
            },
            "daily_trend": daily_trend,
            "top_dishes": top_dishes,
            "loss_ratio_trend": loss_ratio_trend,
        },
    }
