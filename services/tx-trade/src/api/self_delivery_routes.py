"""
外卖自营配送调度MVP
Y-M4

配送单管理（6状态机）+ 配送员管理 + 配送统计
"""
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/delivery", tags=["self-delivery"])

# ─── 状态机定义 ───────────────────────────────────────────────────────────────
# pending → assigned → picked_up → delivering → delivered
#        ↘(任意可失败)→ failed

_VALID_STATUSES = {"pending", "assigned", "picked_up", "delivering", "delivered", "failed"}

_FORWARD_MAP: dict[str, set[str]] = {
    "pending": {"assigned", "failed"},
    "assigned": {"picked_up", "failed"},
    "picked_up": {"delivering", "failed"},
    "delivering": {"delivered", "failed"},
    "delivered": set(),
    "failed": set(),
}

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _calc_estimated_minutes(distance_meters: int) -> int:
    """距离估算配送时长：max(15, distance_meters / 250) 取整（分钟）"""
    return max(15, int(distance_meters / 250))


def _today_str() -> str:
    return date.today().isoformat()


def _row_to_dict(row) -> dict:
    """将 SQLAlchemy Row 转为可序列化 dict，时间戳转 ISO 字符串。"""
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class CreateDeliveryOrderReq(BaseModel):
    order_id: str = Field(..., description="关联交易订单ID")
    store_id: str = Field(..., description="门店ID")
    delivery_address: str = Field(..., min_length=1, description="配送地址")
    delivery_lat: Optional[float] = Field(None, description="纬度")
    delivery_lng: Optional[float] = Field(None, description="经度")
    distance_meters: int = Field(default=0, ge=0, description="配送距离（米）")
    delivery_fee_fen: int = Field(default=0, ge=0, description="配送费（分）")
    tip_fen: int = Field(default=0, ge=0, description="小费（分）")


class AssignRiderReq(BaseModel):
    rider_id: str = Field(..., description="配送员ID")
    rider_name: str = Field(..., min_length=1, max_length=50)
    rider_phone: str = Field(..., min_length=1, max_length=20)


class FailReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="失败原因")


# ─── 1. 配送单列表 ────────────────────────────────────────────────────────────

@router.get("/orders", summary="配送单列表")
async def list_delivery_orders(
    status: Optional[str] = Query(None, description="状态过滤"),
    store_id: Optional[str] = Query(None, description="门店ID过滤"),
    rider_id: Optional[str] = Query(None, description="配送员ID过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出配送单，支持状态/门店/配送员多维过滤。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效状态 '{status}'，合法值: {sorted(_VALID_STATUSES)}",
        )

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        conditions = ["tenant_id = :tenant_id", "is_deleted = false"]
        params: dict = {"tenant_id": x_tenant_id}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if store_id:
            conditions.append("store_id = :store_id::uuid")
            params["store_id"] = store_id
        if rider_id:
            conditions.append("rider_id = :rider_id::uuid")
            params["rider_id"] = rider_id

        where_clause = " AND ".join(conditions)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM self_delivery_orders WHERE {where_clause}"),
            params,
        )
        total: int = count_result.scalar_one()

        offset = (page - 1) * size
        rows = await db.execute(
            text(
                f"SELECT * FROM self_delivery_orders WHERE {where_clause} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": offset},
        )
        items = [_row_to_dict(r) for r in rows]
        return _ok({"items": items, "total": total, "page": page, "size": size})

    except SQLAlchemyError as exc:
        logger.warning("self_delivery.list_orders.db_error", error=str(exc))
        return _ok({"items": [], "total": 0, "page": page, "size": size})


# ─── 2. 创建配送单 ────────────────────────────────────────────────────────────

@router.post("/orders", summary="创建配送单", status_code=201)
async def create_delivery_order(
    req: CreateDeliveryOrderReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    创建自营配送单，自动计算预计配送时长：
    estimated_minutes = max(15, distance_meters / 250)
    """
    estimated_minutes = _calc_estimated_minutes(req.distance_meters)
    delivery_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        await db.execute(
            text("""
                INSERT INTO self_delivery_orders (
                    id, tenant_id, order_id, store_id,
                    delivery_address, delivery_lat, delivery_lng,
                    distance_meters, estimated_minutes,
                    delivery_fee_fen, tip_fen,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :order_id::uuid, :store_id::uuid,
                    :delivery_address, :delivery_lat, :delivery_lng,
                    :distance_meters, :estimated_minutes,
                    :delivery_fee_fen, :tip_fen,
                    'pending', :now, :now
                )
            """),
            {
                "id": delivery_id,
                "tenant_id": x_tenant_id,
                "order_id": req.order_id,
                "store_id": req.store_id,
                "delivery_address": req.delivery_address,
                "delivery_lat": req.delivery_lat,
                "delivery_lng": req.delivery_lng,
                "distance_meters": req.distance_meters,
                "estimated_minutes": estimated_minutes,
                "delivery_fee_fen": req.delivery_fee_fen,
                "tip_fen": req.tip_fen,
                "now": now,
            },
        )
        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("self_delivery.create_order.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建配送单失败，请重试")

    order = {
        "id": delivery_id,
        "order_id": req.order_id,
        "store_id": req.store_id,
        "delivery_address": req.delivery_address,
        "delivery_lat": req.delivery_lat,
        "delivery_lng": req.delivery_lng,
        "distance_meters": req.distance_meters,
        "estimated_minutes": estimated_minutes,
        "actual_minutes": None,
        "rider_id": None,
        "rider_name": None,
        "rider_phone": None,
        "status": "pending",
        "dispatch_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "failed_reason": None,
        "delivery_fee_fen": req.delivery_fee_fen,
        "tip_fen": req.tip_fen,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    logger.info(
        "self_delivery.order_created",
        delivery_id=delivery_id,
        order_id=req.order_id,
        distance_meters=req.distance_meters,
        estimated_minutes=estimated_minutes,
    )
    return _ok(order)


# ─── 3. 派单给配送员 ──────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/assign", summary="派单给配送员")
async def assign_rider(
    delivery_id: str,
    req: AssignRiderReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    将配送单派给指定配送员。
    状态转换：pending → assigned
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        row = await db.execute(
            text("SELECT * FROM self_delivery_orders WHERE id = :id AND is_deleted = false"),
            {"id": delivery_id},
        )
        order_row = row.first()
    except SQLAlchemyError as exc:
        logger.error("self_delivery.assign.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")

    if order_row is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    order = _row_to_dict(order_row)
    allowed = _FORWARD_MAP.get(order["status"], set())
    if "assigned" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许派单，合法目标: {sorted(allowed) or '无'}",
        )

    now = datetime.now(timezone.utc)
    try:
        await db.execute(
            text("""
                UPDATE self_delivery_orders SET
                    rider_id = :rider_id::uuid,
                    rider_name = :rider_name,
                    rider_phone = :rider_phone,
                    status = 'assigned',
                    dispatch_at = :now,
                    updated_at = :now
                WHERE id = :id
            """),
            {
                "rider_id": req.rider_id,
                "rider_name": req.rider_name,
                "rider_phone": req.rider_phone,
                "now": now,
                "id": delivery_id,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("self_delivery.assign.update_error", error=str(exc))
        raise HTTPException(status_code=500, detail="派单更新失败")

    order.update({
        "rider_id": req.rider_id,
        "rider_name": req.rider_name,
        "rider_phone": req.rider_phone,
        "status": "assigned",
        "dispatch_at": now.isoformat(),
        "updated_at": now.isoformat(),
    })

    logger.info(
        "self_delivery.assigned",
        delivery_id=delivery_id,
        rider_id=req.rider_id,
        rider_name=req.rider_name,
    )
    return _ok(order)


# ─── 4. 确认取货 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/pickup", summary="确认取货")
async def confirm_pickup(
    delivery_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    配送员到店取货确认。
    状态转换：assigned → picked_up，记录 picked_up_at
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        row = await db.execute(
            text("SELECT * FROM self_delivery_orders WHERE id = :id AND is_deleted = false"),
            {"id": delivery_id},
        )
        order_row = row.first()
    except SQLAlchemyError as exc:
        logger.error("self_delivery.pickup.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")

    if order_row is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    order = _row_to_dict(order_row)
    allowed = _FORWARD_MAP.get(order["status"], set())
    if "picked_up" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许取货，合法目标: {sorted(allowed) or '无'}",
        )

    now = datetime.now(timezone.utc)
    try:
        await db.execute(
            text("""
                UPDATE self_delivery_orders SET
                    status = 'picked_up',
                    picked_up_at = :now,
                    updated_at = :now
                WHERE id = :id
            """),
            {"now": now, "id": delivery_id},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("self_delivery.pickup.update_error", error=str(exc))
        raise HTTPException(status_code=500, detail="取货确认更新失败")

    order.update({
        "status": "picked_up",
        "picked_up_at": now.isoformat(),
        "updated_at": now.isoformat(),
    })

    logger.info("self_delivery.picked_up", delivery_id=delivery_id)
    return _ok(order)


# ─── 5. 确认送达 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/complete", summary="确认送达")
async def complete_delivery(
    delivery_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    配送完成确认。
    状态转换：picked_up/delivering → delivered，记录 delivered_at，计算 actual_minutes
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        row = await db.execute(
            text("SELECT * FROM self_delivery_orders WHERE id = :id AND is_deleted = false"),
            {"id": delivery_id},
        )
        order_row = row.first()
    except SQLAlchemyError as exc:
        logger.error("self_delivery.complete.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")

    if order_row is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    order = _row_to_dict(order_row)
    allowed = _FORWARD_MAP.get(order["status"], set())
    if "delivered" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许完成，合法目标: {sorted(allowed) or '无'}",
        )

    now = datetime.now(timezone.utc)

    # 计算实际配送时长
    actual_minutes: Optional[int] = None
    ref_time_str = order.get("picked_up_at") or order.get("dispatch_at")
    if ref_time_str:
        try:
            ref_time = datetime.fromisoformat(ref_time_str)
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            delta_seconds = (now - ref_time).total_seconds()
            actual_minutes = max(1, int(delta_seconds / 60))
        except ValueError:
            actual_minutes = None

    try:
        await db.execute(
            text("""
                UPDATE self_delivery_orders SET
                    status = 'delivered',
                    delivered_at = :now,
                    actual_minutes = :actual_minutes,
                    updated_at = :now
                WHERE id = :id
            """),
            {"now": now, "actual_minutes": actual_minutes, "id": delivery_id},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("self_delivery.complete.update_error", error=str(exc))
        raise HTTPException(status_code=500, detail="送达确认更新失败")

    order.update({
        "status": "delivered",
        "delivered_at": now.isoformat(),
        "actual_minutes": actual_minutes,
        "updated_at": now.isoformat(),
    })

    logger.info(
        "self_delivery.completed",
        delivery_id=delivery_id,
        actual_minutes=actual_minutes,
    )
    return _ok(order)


# ─── 6. 配送失败 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/fail", summary="配送失败")
async def fail_delivery(
    delivery_id: str,
    req: FailReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    标记配送失败并记录失败原因。
    任何非终态（delivered）均可转为 failed。
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        row = await db.execute(
            text("SELECT * FROM self_delivery_orders WHERE id = :id AND is_deleted = false"),
            {"id": delivery_id},
        )
        order_row = row.first()
    except SQLAlchemyError as exc:
        logger.error("self_delivery.fail.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")

    if order_row is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    order = _row_to_dict(order_row)
    if order["status"] == "delivered":
        raise HTTPException(status_code=409, detail="已送达的配送单不能标记为失败")
    if order["status"] == "failed":
        raise HTTPException(status_code=409, detail="配送单已处于失败状态")

    now = datetime.now(timezone.utc)
    try:
        await db.execute(
            text("""
                UPDATE self_delivery_orders SET
                    status = 'failed',
                    failed_reason = :reason,
                    updated_at = :now
                WHERE id = :id
            """),
            {"reason": req.reason, "now": now, "id": delivery_id},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("self_delivery.fail.update_error", error=str(exc))
        raise HTTPException(status_code=500, detail="失败标记更新失败")

    order.update({
        "status": "failed",
        "failed_reason": req.reason,
        "updated_at": now.isoformat(),
    })

    logger.info("self_delivery.failed", delivery_id=delivery_id, reason=req.reason)
    return _ok(order)


# ─── 7. 配送员列表 ────────────────────────────────────────────────────────────

@router.get("/riders", summary="配送员列表（在线/离线/配送中）")
async def list_riders(
    status: Optional[str] = Query(
        None, description="状态过滤：online/offline/delivering"
    ),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    列出配送员及其当前工作状态，派生自 self_delivery_orders 在途数据。
    有在途单（assigned/picked_up/delivering）= delivering，
    否则视为 online（无法从 DB 区分 online/offline，该字段依赖骑手 App 心跳，
    暂以有今日完成单=online，其余=offline 作为合理近似）。
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        today = _today_str()
        rows = await db.execute(
            text("""
                SELECT
                    rider_id::text,
                    rider_name,
                    rider_phone,
                    COUNT(*) FILTER (WHERE status IN ('assigned','picked_up','delivering')) AS current_orders,
                    COUNT(*) FILTER (WHERE status = 'delivered' AND delivered_at::date = :today) AS today_completed
                FROM self_delivery_orders
                WHERE tenant_id = :tenant_id
                  AND rider_id IS NOT NULL
                  AND is_deleted = false
                GROUP BY rider_id, rider_name, rider_phone
            """),
            {"tenant_id": x_tenant_id, "today": today},
        )
        riders = []
        for r in rows:
            current = int(r.current_orders or 0)
            today_done = int(r.today_completed or 0)
            derived_status = "delivering" if current > 0 else ("online" if today_done > 0 else "offline")
            riders.append({
                "id": str(r.rider_id),
                "name": r.rider_name,
                "phone": r.rider_phone,
                "status": derived_status,
                "current_orders": current,
                "today_completed": today_done,
            })
    except SQLAlchemyError as exc:
        logger.warning("self_delivery.list_riders.db_error", error=str(exc))
        riders = []

    if status:
        riders = [r for r in riders if r["status"] == status]

    return _ok({"items": riders, "total": len(riders)})


# ─── 8. 配送员工作量 ──────────────────────────────────────────────────────────

@router.get("/riders/{rider_id}/workload", summary="配送员当前工作量")
async def get_rider_workload(
    rider_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    查询配送员工作量：
    - 在途单数（current_orders）
    - 今日完成数（today_completed）
    - 当前状态
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        today = _today_str()
        row = await db.execute(
            text("""
                SELECT
                    rider_id::text,
                    rider_name,
                    rider_phone,
                    COUNT(*) FILTER (WHERE status IN ('assigned','picked_up','delivering')) AS current_orders,
                    COUNT(*) FILTER (WHERE status = 'delivered' AND delivered_at::date = :today) AS today_completed,
                    ARRAY_AGG(id::text) FILTER (WHERE status IN ('assigned','picked_up','delivering')) AS in_transit_ids
                FROM self_delivery_orders
                WHERE tenant_id = :tenant_id
                  AND rider_id = :rider_id::uuid
                  AND is_deleted = false
                GROUP BY rider_id, rider_name, rider_phone
            """),
            {"tenant_id": x_tenant_id, "rider_id": rider_id, "today": today},
        )
        rider_row = row.first()
    except SQLAlchemyError as exc:
        logger.warning("self_delivery.rider_workload.db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    if rider_row is None:
        raise HTTPException(status_code=404, detail=f"配送员 '{rider_id}' 不存在")

    current = int(rider_row.current_orders or 0)
    today_done = int(rider_row.today_completed or 0)
    in_transit_ids = [str(i) for i in (rider_row.in_transit_ids or []) if i]
    derived_status = "delivering" if current > 0 else ("online" if today_done > 0 else "offline")

    return _ok({
        "rider_id": rider_id,
        "name": rider_row.rider_name,
        "phone": rider_row.rider_phone,
        "status": derived_status,
        "current_orders": current,
        "today_completed": today_done,
        "in_transit_order_ids": in_transit_ids,
    })


# ─── 9. 配送统计 ──────────────────────────────────────────────────────────────

@router.get("/stats", summary="配送统计（今日）")
async def get_delivery_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    今日配送效率统计：
    - 派单数
    - 完成数
    - 平均配送时长（分钟）
    - 准时率（actual_minutes ≤ estimated_minutes）
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        today = _today_str()
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                        AS dispatched_count,
                    COUNT(*) FILTER (WHERE status = 'delivered')                   AS completed_count,
                    COUNT(*) FILTER (WHERE status = 'failed')                      AS failed_count,
                    COUNT(*) FILTER (WHERE status IN ('pending','assigned','picked_up','delivering')) AS pending_count,
                    AVG(actual_minutes) FILTER (WHERE status = 'delivered' AND actual_minutes IS NOT NULL) AS avg_minutes,
                    COUNT(*) FILTER (
                        WHERE status = 'delivered'
                          AND actual_minutes IS NOT NULL
                          AND estimated_minutes IS NOT NULL
                          AND actual_minutes <= estimated_minutes
                    )                                                               AS on_time_count,
                    COUNT(DISTINCT rider_id) FILTER (
                        WHERE status IN ('assigned','picked_up','delivering')
                    )                                                               AS rider_count_online
                FROM self_delivery_orders
                WHERE tenant_id = :tenant_id
                  AND created_at::date = :today
                  AND is_deleted = false
            """),
            {"tenant_id": x_tenant_id, "today": today},
        )
        stats_row = row.first()
    except SQLAlchemyError as exc:
        logger.warning("self_delivery.stats.db_error", error=str(exc))
        stats_row = None

    if stats_row is None:
        return _ok({
            "date": _today_str(),
            "dispatched_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "pending_count": 0,
            "avg_delivery_minutes": 0.0,
            "on_time_rate_percent": 0.0,
            "rider_count_online": 0,
        })

    dispatched = int(stats_row.dispatched_count or 0)
    completed = int(stats_row.completed_count or 0)
    failed = int(stats_row.failed_count or 0)
    pending = int(stats_row.pending_count or 0)
    avg_minutes = round(float(stats_row.avg_minutes or 0), 1)
    on_time = int(stats_row.on_time_count or 0)
    on_time_rate = round(on_time / completed * 100, 1) if completed > 0 else 0.0
    rider_online = int(stats_row.rider_count_online or 0)

    return _ok({
        "date": _today_str(),
        "dispatched_count": dispatched,
        "completed_count": completed,
        "failed_count": failed,
        "pending_count": pending,
        "avg_delivery_minutes": avg_minutes,
        "on_time_rate_percent": on_time_rate,
        "rider_count_online": rider_online,
    })
