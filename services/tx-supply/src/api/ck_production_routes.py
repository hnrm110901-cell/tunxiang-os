"""中央厨房生产工单 & 配送单 API

端点：
  POST  /api/v1/supply/ck/production-orders                          — 创建生产工单
  GET   /api/v1/supply/ck/production-orders                          — 查询工单列表
  PATCH /api/v1/supply/ck/production-orders/{order_id}/status        — 推进状态
  POST  /api/v1/supply/ck/production-orders/{order_id}/smart-plan    — 智能排产建议
  GET   /api/v1/supply/ck/distribution-orders                        — 查询配送单列表
  POST  /api/v1/supply/ck/distribution-orders                        — 创建配送单
  PATCH /api/v1/supply/ck/distribution-orders/{dist_id}/receive      — 门店确认收货

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply/ck", tags=["ck_production"])

# 状态转移规则：key=当前状态，value=允许转入的目标状态集合
_PRODUCTION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"confirmed", "cancelled"},
    "confirmed": {"producing", "cancelled"},
    "producing": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

_DISTRIBUTION_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"shipped", "cancelled"},
    "shipped":   {"received"},
    "received":  {"confirmed"},
    "confirmed": set(),
    "cancelled": set(),
}

# ─── 请求体模型 ────────────────────────────────────────────────────────────────


class ProductionItemIn(BaseModel):
    dish_id: str = Field(..., description="菜品UUID")
    dish_name: str = Field(..., min_length=1, max_length=100)
    quantity: Decimal = Field(..., gt=Decimal("0"))
    unit: str = Field("份", max_length=20)
    bom_id: Optional[str] = Field(None, description="指定BOM版本ID，不传则用激活版本")
    estimated_cost_fen: int = Field(0, ge=0, description="预估成本（分）")


class ProductionOrderCreate(BaseModel):
    store_id: str = Field(..., description="中央厨房门店ID")
    production_date: str = Field(..., description="生产日期 YYYY-MM-DD")
    notes: Optional[str] = Field(None, max_length=500)
    items: List[ProductionItemIn] = Field(..., min_length=1, description="生产明细，至少一行")


class StatusPatch(BaseModel):
    status: str = Field(..., description="目标状态")
    notes: Optional[str] = Field(None, max_length=300, description="状态变更备注")


class DistributionItemIn(BaseModel):
    dish_id: str = Field(..., description="菜品UUID")
    dish_name: str = Field(..., min_length=1, max_length=100)
    quantity: Decimal = Field(..., gt=Decimal("0"))
    unit: str = Field("份", max_length=20)
    bom_id: Optional[str] = None
    estimated_cost_fen: int = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=300)


class DistributionOrderCreate(BaseModel):
    from_kitchen_id: str = Field(..., description="发货方中央厨房ID（store_id格式）")
    to_store_id: str = Field(..., description="收货方门店ID")
    distribution_date: str = Field(..., description="计划配送日期 YYYY-MM-DD")
    carrier_name: Optional[str] = Field(None, max_length=50, description="承运人/司机")
    tracking_no: Optional[str] = Field(None, max_length=100, description="物流单号")
    notes: Optional[str] = Field(None, max_length=500)
    items: List[DistributionItemIn] = Field(..., min_length=1)


class ReceiveItemIn(BaseModel):
    dish_id: str = Field(..., description="菜品UUID")
    actual_received_qty: Decimal = Field(..., ge=Decimal("0"), description="实收数量")
    notes: Optional[str] = Field(None, max_length=300, description="差异备注")


class ReceiveConfirmIn(BaseModel):
    items: List[ReceiveItemIn] = Field(..., min_length=1, description="实收明细")
    notes: Optional[str] = Field(None, max_length=500)


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _gen_order_no(prefix: str, date_str: str) -> str:
    """生成工单编号，如 CK-20260402-a3f1。"""
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{date_str.replace('-', '')}-{suffix}"


def _row_to_dict(row) -> dict:
    """将 RowMapping 转为 JSON 友好字典（UUID→str，datetime→isoformat）。"""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = str(v)
        elif hasattr(v, "__str__") and type(v).__name__ == "UUID":
            d[k] = str(v)
    return d


async def _fetch_production_order(
    db: AsyncSession, order_id: str, tenant_id: str
) -> Optional[dict]:
    row = await db.execute(
        text("""
            SELECT id, tenant_id, order_no, store_id, production_date,
                   status, total_items, completed_items, notes,
                   created_at, updated_at
            FROM ck_production_orders
            WHERE id = :oid AND tenant_id = :tid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    main = row.mappings().first()
    if not main:
        return None

    items_row = await db.execute(
        text("""
            SELECT id, dish_id, dish_name, quantity, unit,
                   bom_id, estimated_cost_fen, actual_cost_fen, status
            FROM ck_production_items
            WHERE order_id = :oid AND tenant_id = :tid
            ORDER BY created_at
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    result = _row_to_dict(main)
    result["items"] = [_row_to_dict(r) for r in items_row.mappings().all()]
    return result


async def _fetch_distribution_order(
    db: AsyncSession, dist_id: str, tenant_id: str
) -> Optional[dict]:
    row = await db.execute(
        text("""
            SELECT id, tenant_id, order_no, from_kitchen_id, to_store_id,
                   distribution_date, status, total_items,
                   carrier_name, tracking_no, notes, created_at, updated_at
            FROM ck_distribution_orders
            WHERE id = :did AND tenant_id = :tid
        """),
        {"did": dist_id, "tid": tenant_id},
    )
    main = row.mappings().first()
    if not main:
        return None

    items_row = await db.execute(
        text("""
            SELECT id, dish_id, dish_name, quantity, unit,
                   bom_id, estimated_cost_fen, actual_received_qty, notes
            FROM ck_distribution_items
            WHERE distribution_id = :did AND tenant_id = :tid
            ORDER BY created_at
        """),
        {"did": dist_id, "tid": tenant_id},
    )
    result = _row_to_dict(main)
    result["items"] = [_row_to_dict(r) for r in items_row.mappings().all()]
    return result


# ─── POST /ck/production-orders ───────────────────────────────────────────────


@router.post("/production-orders", status_code=201)
async def create_production_order(
    body: ProductionOrderCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建中央厨房生产工单（初始状态 draft）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        order_no = _gen_order_no("CK", body.production_date)

        order_row = await db.execute(
            text("""
                INSERT INTO ck_production_orders
                  (tenant_id, order_no, store_id, production_date,
                   status, total_items, completed_items, notes)
                VALUES
                  (:tid, :order_no, :store_id, :production_date,
                   'draft', :total_items, 0, :notes)
                RETURNING id
            """),
            {
                "tid": x_tenant_id,
                "order_no": order_no,
                "store_id": body.store_id,
                "production_date": body.production_date,
                "total_items": len(body.items),
                "notes": body.notes,
            },
        )
        order_id = str(order_row.scalar())

        for item in body.items:
            # 若未指定 bom_id，查激活版本
            bom_id = item.bom_id
            estimated_cost = item.estimated_cost_fen
            if not bom_id:
                bom_row = await db.execute(
                    text("""
                        SELECT id, total_cost_fen FROM dish_boms
                        WHERE tenant_id = :tid AND dish_id = :dish_id
                          AND is_active = true AND is_deleted = false
                        LIMIT 1
                    """),
                    {"tid": x_tenant_id, "dish_id": item.dish_id},
                )
                bom = bom_row.mappings().first()
                if bom:
                    bom_id = str(bom["id"])
                    if estimated_cost == 0:
                        estimated_cost = int(float(item.quantity) * (bom["total_cost_fen"] or 0))

            await db.execute(
                text("""
                    INSERT INTO ck_production_items
                      (tenant_id, order_id, dish_id, dish_name, quantity,
                       unit, bom_id, estimated_cost_fen, status)
                    VALUES
                      (:tid, :order_id, :dish_id, :dish_name, :quantity,
                       :unit, :bom_id, :estimated_cost_fen, 'pending')
                """),
                {
                    "tid": x_tenant_id,
                    "order_id": order_id,
                    "dish_id": item.dish_id,
                    "dish_name": item.dish_name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "bom_id": bom_id,
                    "estimated_cost_fen": estimated_cost,
                },
            )

        await db.commit()
        log.info("ck_production_order.created", order_id=order_id, tenant_id=x_tenant_id)

        data = await _fetch_production_order(db, order_id, x_tenant_id)
        return {"ok": True, "data": data}

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_production_order.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库写入失败")


# ─── GET /ck/production-orders ────────────────────────────────────────────────


@router.get("/production-orders")
async def list_production_orders(
    store_id: Optional[str] = Query(None, description="按中央厨房门店ID过滤"),
    date: Optional[str] = Query(None, description="按生产日期过滤 YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询生产工单列表（不含明细行）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        conditions = ["tenant_id = :tid"]
        params: dict = {"tid": x_tenant_id, "offset": (page - 1) * size, "limit": size}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if date:
            conditions.append("production_date = :date")
            params["date"] = date
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM ck_production_orders WHERE {where}"), params
        )
        total = count_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT id, order_no, store_id, production_date,
                       status, total_items, completed_items, notes,
                       created_at, updated_at
                FROM ck_production_orders
                WHERE {where}
                ORDER BY production_date DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_row_to_dict(r) for r in rows.mappings().all()]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("list_production_orders.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询失败")


# ─── PATCH /ck/production-orders/{order_id}/status ───────────────────────────


@router.patch("/production-orders/{order_id}/status")
async def update_production_order_status(
    order_id: str,
    body: StatusPatch,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """推进生产工单状态。允许转移：draft→confirmed→producing→completed（或任意→cancelled）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        row = await db.execute(
            text("""
                SELECT id, status FROM ck_production_orders
                WHERE id = :oid AND tenant_id = :tid
            """),
            {"oid": order_id, "tid": x_tenant_id},
        )
        order = row.mappings().first()
        if not order:
            raise HTTPException(status_code=404, detail="生产工单不存在")

        current = order["status"]
        target = body.status
        allowed = _PRODUCTION_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"状态不可从 {current} 转移到 {target}（允许：{allowed}）",
            )

        # 若转为 completed，同步将 pending/producing 的明细行全部标记为 completed
        if target == "completed":
            await db.execute(
                text("""
                    UPDATE ck_production_items
                    SET status = 'completed'
                    WHERE order_id = :oid AND tenant_id = :tid
                      AND status IN ('pending', 'producing')
                """),
                {"oid": order_id, "tid": x_tenant_id},
            )
            # 更新 completed_items 计数
            count_row = await db.execute(
                text("""
                    SELECT COUNT(*) FROM ck_production_items
                    WHERE order_id = :oid AND tenant_id = :tid AND status = 'completed'
                """),
                {"oid": order_id, "tid": x_tenant_id},
            )
            completed_count = count_row.scalar() or 0
            await db.execute(
                text("""
                    UPDATE ck_production_orders
                    SET status = :target, completed_items = :count,
                        notes = COALESCE(:extra_notes, notes)
                    WHERE id = :oid AND tenant_id = :tid
                """),
                {"target": target, "count": completed_count,
                 "extra_notes": body.notes, "oid": order_id, "tid": x_tenant_id},
            )
        else:
            await db.execute(
                text("""
                    UPDATE ck_production_orders
                    SET status = :target,
                        notes = COALESCE(:extra_notes, notes)
                    WHERE id = :oid AND tenant_id = :tid
                """),
                {"target": target, "extra_notes": body.notes,
                 "oid": order_id, "tid": x_tenant_id},
            )

        await db.commit()
        log.info(
            "ck_production_order.status_updated",
            order_id=order_id, from_=current, to=target,
        )

        data = await _fetch_production_order(db, order_id, x_tenant_id)
        return {"ok": True, "data": data}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("update_production_order_status.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="状态更新失败")


# ─── POST /ck/production-orders/{order_id}/smart-plan ─────────────────────────


@router.post("/production-orders/{order_id}/smart-plan")
async def smart_plan(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """智能排产：根据门店近7天历史销量均值自动生成生产数量建议。

    算法：
    1. 查询本工单关联的所有菜品
    2. 对每个菜品查询 order_items（近7天）平均日销量
    3. 生成建议数量 = 7日均值 × 1.1（10%安全库存系数）
    4. 周末日期额外 × 1.3（沿用项目惯例）
    """
    try:
        await _set_tenant(db, x_tenant_id)

        order_row = await db.execute(
            text("""
                SELECT id, store_id, production_date, status
                FROM ck_production_orders
                WHERE id = :oid AND tenant_id = :tid
            """),
            {"oid": order_id, "tid": x_tenant_id},
        )
        order = order_row.mappings().first()
        if not order:
            raise HTTPException(status_code=404, detail="生产工单不存在")

        production_date = order["production_date"]
        # 判断是否为周末
        if isinstance(production_date, str):
            pd = datetime.date.fromisoformat(production_date)
        else:
            pd = production_date
        is_weekend = pd.weekday() >= 5  # 5=Saturday, 6=Sunday
        weekend_factor = 1.3 if is_weekend else 1.0

        items_row = await db.execute(
            text("""
                SELECT id, dish_id, dish_name, quantity AS planned_qty, unit
                FROM ck_production_items
                WHERE order_id = :oid AND tenant_id = :tid
                ORDER BY created_at
            """),
            {"oid": order_id, "tid": x_tenant_id},
        )
        items = items_row.mappings().all()

        suggestions = []
        for item in items:
            dish_id = str(item["dish_id"])

            # 查询近7天历史销量（从 order_items 表，逻辑引用）
            # 若 order_items 表不存在，gracefully 返回 0
            avg_qty: float = 0.0
            try:
                sales_row = await db.execute(
                    text("""
                        SELECT COALESCE(SUM(oi.quantity), 0) / 7.0 AS avg_daily
                        FROM order_items oi
                        JOIN orders o ON o.id = oi.order_id
                        WHERE oi.dish_id = :dish_id
                          AND oi.tenant_id = :tid
                          AND o.store_id = :store_id
                          AND o.created_at >= now() - INTERVAL '7 days'
                          AND o.is_deleted = false
                          AND oi.is_deleted = false
                    """),
                    {
                        "dish_id": dish_id,
                        "tid": x_tenant_id,
                        "store_id": str(order["store_id"]),
                    },
                )
                avg_qty = float(sales_row.scalar() or 0)
            except SQLAlchemyError:
                # order_items 表可能不在此服务 schema 中，忽略
                avg_qty = 0.0

            suggested = round(avg_qty * 1.1 * weekend_factor, 1) if avg_qty > 0 else None

            suggestions.append({
                "item_id": str(item["id"]),
                "dish_id": dish_id,
                "dish_name": item["dish_name"],
                "planned_qty": str(item["planned_qty"]),
                "unit": item["unit"],
                "avg_daily_sales_7d": round(avg_qty, 2),
                "suggested_qty": suggested,
                "is_weekend": is_weekend,
                "weekend_factor": weekend_factor,
                "note": (
                    "建议数量 = 7日均值 × 1.1（安全系数）"
                    + (" × 1.3（周末加成）" if is_weekend else "")
                ) if suggested else "近7天无销售数据，建议手动填写",
            })

        return {"ok": True, "data": {
            "order_id": order_id,
            "production_date": production_date.isoformat() if hasattr(production_date, "isoformat") else str(production_date),
            "is_weekend": is_weekend,
            "suggestions": suggestions,
        }}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("smart_plan.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="智能排产查询失败")


# ─── GET /ck/distribution-orders ─────────────────────────────────────────────


@router.get("/distribution-orders")
async def list_distribution_orders(
    to_store_id: Optional[str] = Query(None, description="按收货门店ID过滤"),
    date: Optional[str] = Query(None, description="按配送日期过滤 YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    from_kitchen_id: Optional[str] = Query(None, description="按发货厨房ID过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询配送单列表（不含明细行）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        conditions = ["tenant_id = :tid"]
        params: dict = {"tid": x_tenant_id, "offset": (page - 1) * size, "limit": size}

        if to_store_id:
            conditions.append("to_store_id = :to_store_id")
            params["to_store_id"] = to_store_id
        if date:
            conditions.append("distribution_date = :date")
            params["date"] = date
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if from_kitchen_id:
            conditions.append("from_kitchen_id = :from_kitchen_id")
            params["from_kitchen_id"] = from_kitchen_id

        where = " AND ".join(conditions)

        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM ck_distribution_orders WHERE {where}"), params
        )
        total = count_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT id, order_no, from_kitchen_id, to_store_id,
                       distribution_date, status, total_items,
                       carrier_name, tracking_no, notes,
                       created_at, updated_at
                FROM ck_distribution_orders
                WHERE {where}
                ORDER BY distribution_date DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_row_to_dict(r) for r in rows.mappings().all()]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("list_distribution_orders.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询失败")


# ─── POST /ck/distribution-orders ─────────────────────────────────────────────


@router.post("/distribution-orders", status_code=201)
async def create_distribution_order(
    body: DistributionOrderCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建中央厨房→门店配送单（初始状态 pending）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        order_no = _gen_order_no("CKD", body.distribution_date)

        dist_row = await db.execute(
            text("""
                INSERT INTO ck_distribution_orders
                  (tenant_id, order_no, from_kitchen_id, to_store_id,
                   distribution_date, status, total_items,
                   carrier_name, tracking_no, notes)
                VALUES
                  (:tid, :order_no, :from_kitchen_id, :to_store_id,
                   :distribution_date, 'pending', :total_items,
                   :carrier_name, :tracking_no, :notes)
                RETURNING id
            """),
            {
                "tid": x_tenant_id,
                "order_no": order_no,
                "from_kitchen_id": body.from_kitchen_id,
                "to_store_id": body.to_store_id,
                "distribution_date": body.distribution_date,
                "total_items": len(body.items),
                "carrier_name": body.carrier_name,
                "tracking_no": body.tracking_no,
                "notes": body.notes,
            },
        )
        dist_id = str(dist_row.scalar())

        for item in body.items:
            await db.execute(
                text("""
                    INSERT INTO ck_distribution_items
                      (tenant_id, distribution_id, dish_id, dish_name,
                       quantity, unit, bom_id, estimated_cost_fen, notes)
                    VALUES
                      (:tid, :dist_id, :dish_id, :dish_name,
                       :quantity, :unit, :bom_id, :estimated_cost_fen, :notes)
                """),
                {
                    "tid": x_tenant_id,
                    "dist_id": dist_id,
                    "dish_id": item.dish_id,
                    "dish_name": item.dish_name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "bom_id": item.bom_id,
                    "estimated_cost_fen": item.estimated_cost_fen,
                    "notes": item.notes,
                },
            )

        await db.commit()
        log.info("ck_distribution_order.created", dist_id=dist_id, tenant_id=x_tenant_id)

        data = await _fetch_distribution_order(db, dist_id, x_tenant_id)
        return {"ok": True, "data": data}

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_distribution_order.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库写入失败")


# ─── PATCH /ck/distribution-orders/{dist_id}/receive ─────────────────────────


@router.patch("/distribution-orders/{dist_id}/receive")
async def receive_distribution_order(
    dist_id: str,
    body: ReceiveConfirmIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """门店确认收货。

    - 将配送单状态推进为 received
    - 按 dish_id 匹配更新 ck_distribution_items.actual_received_qty
    - 自动检测差异（实收 vs 计划）超过5%时在 notes 中追加差异说明
    """
    try:
        await _set_tenant(db, x_tenant_id)

        dist_row = await db.execute(
            text("""
                SELECT id, status FROM ck_distribution_orders
                WHERE id = :did AND tenant_id = :tid
            """),
            {"did": dist_id, "tid": x_tenant_id},
        )
        dist = dist_row.mappings().first()
        if not dist:
            raise HTTPException(status_code=404, detail="配送单不存在")

        current = dist["status"]
        allowed = _DISTRIBUTION_STATUS_TRANSITIONS.get(current, set())
        if "received" not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"配送单当前状态 {current} 不可确认收货（需为 shipped 状态）",
            )

        # 更新各明细行实收数量
        for recv_item in body.items:
            # 查对应明细行计划数量（用于差异检测）
            plan_row = await db.execute(
                text("""
                    SELECT id, quantity FROM ck_distribution_items
                    WHERE distribution_id = :did AND tenant_id = :tid
                      AND dish_id = :dish_id
                    LIMIT 1
                """),
                {"did": dist_id, "tid": x_tenant_id, "dish_id": recv_item.dish_id},
            )
            plan = plan_row.mappings().first()
            if not plan:
                continue

            planned = float(plan["quantity"])
            received = float(recv_item.actual_received_qty)

            item_notes = recv_item.notes or ""
            if planned > 0:
                diff_pct = abs(received - planned) / planned
                if diff_pct > 0.05:
                    variance_msg = (
                        f"[差异提醒] 计划{planned}，实收{received}，"
                        f"偏差{round(diff_pct * 100, 1)}%"
                    )
                    item_notes = f"{item_notes} {variance_msg}".strip()

            await db.execute(
                text("""
                    UPDATE ck_distribution_items
                    SET actual_received_qty = :qty,
                        notes = :notes
                    WHERE id = :item_id AND tenant_id = :tid
                """),
                {
                    "qty": str(recv_item.actual_received_qty),
                    "notes": item_notes or None,
                    "item_id": str(plan["id"]),
                    "tid": x_tenant_id,
                },
            )

        # 更新配送单状态
        await db.execute(
            text("""
                UPDATE ck_distribution_orders
                SET status = 'received',
                    notes = COALESCE(:extra_notes, notes)
                WHERE id = :did AND tenant_id = :tid
            """),
            {"extra_notes": body.notes, "did": dist_id, "tid": x_tenant_id},
        )

        await db.commit()
        log.info("ck_distribution_order.received", dist_id=dist_id, tenant_id=x_tenant_id)

        data = await _fetch_distribution_order(db, dist_id, x_tenant_id)
        return {"ok": True, "data": data}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("receive_distribution_order.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="收货确认失败")
