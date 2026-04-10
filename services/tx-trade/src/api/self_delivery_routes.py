"""
外卖自营配送调度MVP
Y-M4

配送单管理（6状态机）+ 配送员管理 + 配送统计
"""
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/delivery", tags=["self-delivery"])

# ─── Mock 数据 ────────────────────────────────────────────────────────────────

MOCK_RIDERS: list[dict] = [
    {
        "id": "rider-001",
        "name": "张配送",
        "phone": "138xxxx0001",
        "status": "delivering",
        "current_orders": 2,
        "today_completed": 8,
    },
    {
        "id": "rider-002",
        "name": "李骑手",
        "phone": "139xxxx0002",
        "status": "online",
        "current_orders": 0,
        "today_completed": 5,
    },
    {
        "id": "rider-003",
        "name": "王小跑",
        "phone": "137xxxx0003",
        "status": "offline",
        "current_orders": 0,
        "today_completed": 3,
    },
]

# 内存存储配送单（生产替换 DB）
_MOCK_DELIVERY_ORDERS: list[dict] = []

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


def _find_order(delivery_id: str) -> dict | None:
    for o in _MOCK_DELIVERY_ORDERS:
        if o["id"] == delivery_id:
            return o
    return None


def _find_rider(rider_id: str) -> dict | None:
    for r in MOCK_RIDERS:
        if r["id"] == rider_id:
            return r
    return None


def _calc_estimated_minutes(distance_meters: int) -> int:
    """距离估算配送时长：max(15, distance_meters / 250) 取整（分钟）"""
    return max(15, int(distance_meters / 250))


def _today_str() -> str:
    return date.today().isoformat()


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
) -> dict:
    """列出配送单，支持状态/门店/配送员多维过滤。"""
    orders = list(_MOCK_DELIVERY_ORDERS)

    if status:
        if status not in _VALID_STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"无效状态 '{status}'，合法值: {sorted(_VALID_STATUSES)}")
        orders = [o for o in orders if o["status"] == status]
    if store_id:
        orders = [o for o in orders if o["store_id"] == store_id]
    if rider_id:
        orders = [o for o in orders if o.get("rider_id") == rider_id]

    total = len(orders)
    start = (page - 1) * size
    items = orders[start: start + size]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── 2. 创建配送单 ────────────────────────────────────────────────────────────

@router.post("/orders", summary="创建配送单", status_code=201)
async def create_delivery_order(req: CreateDeliveryOrderReq) -> dict:
    """
    创建自营配送单，自动计算预计配送时长：
    estimated_minutes = max(15, distance_meters / 250)
    """
    estimated_minutes = _calc_estimated_minutes(req.distance_meters)
    delivery_id = f"DLV-{uuid.uuid4().hex[:12].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    order: dict = {
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
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    _MOCK_DELIVERY_ORDERS.append(order)

    logger.info("self_delivery.order_created",
                delivery_id=delivery_id,
                order_id=req.order_id,
                distance_meters=req.distance_meters,
                estimated_minutes=estimated_minutes)

    return _ok(order)


# ─── 3. 派单给配送员 ──────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/assign", summary="派单给配送员")
async def assign_rider(delivery_id: str, req: AssignRiderReq) -> dict:
    """
    将配送单派给指定配送员。
    状态转换：pending → assigned
    """
    order = _find_order(delivery_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    allowed = _FORWARD_MAP.get(order["status"], set())
    if "assigned" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许派单，合法目标: {sorted(allowed) or '无'}",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    order.update({
        "rider_id": req.rider_id,
        "rider_name": req.rider_name,
        "rider_phone": req.rider_phone,
        "status": "assigned",
        "dispatch_at": now_iso,
        "updated_at": now_iso,
    })

    # 更新 mock 配送员工作量
    rider = _find_rider(req.rider_id)
    if rider:
        rider["current_orders"] = rider.get("current_orders", 0) + 1
        if rider["status"] == "online":
            rider["status"] = "delivering"

    logger.info("self_delivery.assigned",
                delivery_id=delivery_id,
                rider_id=req.rider_id,
                rider_name=req.rider_name)

    return _ok(order)


# ─── 4. 确认取货 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/pickup", summary="确认取货")
async def confirm_pickup(delivery_id: str) -> dict:
    """
    配送员到店取货确认。
    状态转换：assigned → picked_up，记录 picked_up_at
    """
    order = _find_order(delivery_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    allowed = _FORWARD_MAP.get(order["status"], set())
    if "picked_up" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许取货，合法目标: {sorted(allowed) or '无'}",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    order.update({
        "status": "picked_up",
        "picked_up_at": now_iso,
        "updated_at": now_iso,
    })

    logger.info("self_delivery.picked_up", delivery_id=delivery_id)
    return _ok(order)


# ─── 5. 确认送达 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/complete", summary="确认送达")
async def complete_delivery(delivery_id: str) -> dict:
    """
    配送完成确认。
    状态转换：picked_up/delivering → delivered，记录 delivered_at，计算 actual_minutes
    """
    order = _find_order(delivery_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    allowed = _FORWARD_MAP.get(order["status"], set())
    if "delivered" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 '{order['status']}' 不允许完成，合法目标: {sorted(allowed) or '无'}",
        )

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # 计算实际配送时长
    actual_minutes: Optional[int] = None
    ref_time_str = order.get("picked_up_at") or order.get("dispatch_at")
    if ref_time_str:
        try:
            ref_time = datetime.fromisoformat(ref_time_str)
            delta_seconds = (now - ref_time).total_seconds()
            actual_minutes = max(1, int(delta_seconds / 60))
        except ValueError:
            actual_minutes = None

    order.update({
        "status": "delivered",
        "delivered_at": now_iso,
        "actual_minutes": actual_minutes,
        "updated_at": now_iso,
    })

    # 更新 mock 配送员工作量
    rider_id = order.get("rider_id")
    if rider_id:
        rider = _find_rider(rider_id)
        if rider:
            rider["current_orders"] = max(0, rider.get("current_orders", 1) - 1)
            rider["today_completed"] = rider.get("today_completed", 0) + 1
            if rider["current_orders"] == 0:
                rider["status"] = "online"

    logger.info("self_delivery.completed",
                delivery_id=delivery_id,
                actual_minutes=actual_minutes)
    return _ok(order)


# ─── 6. 配送失败 ──────────────────────────────────────────────────────────────

@router.post("/orders/{delivery_id}/fail", summary="配送失败")
async def fail_delivery(delivery_id: str, req: FailReq) -> dict:
    """
    标记配送失败并记录失败原因。
    任何非终态（delivered）均可转为 failed。
    """
    order = _find_order(delivery_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"配送单 '{delivery_id}' 不存在")

    if order["status"] == "delivered":
        raise HTTPException(
            status_code=409,
            detail="已送达的配送单不能标记为失败",
        )
    if order["status"] == "failed":
        raise HTTPException(
            status_code=409,
            detail="配送单已处于失败状态",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    order.update({
        "status": "failed",
        "failed_reason": req.reason,
        "updated_at": now_iso,
    })

    # 更新 mock 配送员工作量
    rider_id = order.get("rider_id")
    if rider_id:
        rider = _find_rider(rider_id)
        if rider:
            rider["current_orders"] = max(0, rider.get("current_orders", 1) - 1)
            if rider["current_orders"] == 0:
                rider["status"] = "online"

    logger.info("self_delivery.failed",
                delivery_id=delivery_id,
                reason=req.reason)
    return _ok(order)


# ─── 7. 配送员列表 ────────────────────────────────────────────────────────────

@router.get("/riders", summary="配送员列表（在线/离线/配送中）")
async def list_riders(
    status: Optional[str] = Query(None,
                                   description="状态过滤：online/offline/delivering"),
) -> dict:
    """列出配送员及其当前工作状态。"""
    riders = list(MOCK_RIDERS)
    if status:
        riders = [r for r in riders if r["status"] == status]
    return _ok({"items": riders, "total": len(riders)})


# ─── 8. 配送员工作量 ──────────────────────────────────────────────────────────

@router.get("/riders/{rider_id}/workload", summary="配送员当前工作量")
async def get_rider_workload(rider_id: str) -> dict:
    """
    查询配送员工作量：
    - 在途单数（current_orders）
    - 今日完成数（today_completed）
    - 当前状态
    """
    rider = _find_rider(rider_id)
    if rider is None:
        raise HTTPException(status_code=404, detail=f"配送员 '{rider_id}' 不存在")

    # 从内存订单计算实际在途单数
    in_transit_orders = [
        o for o in _MOCK_DELIVERY_ORDERS
        if o.get("rider_id") == rider_id
        and o["status"] in {"assigned", "picked_up", "delivering"}
    ]
    today = _today_str()
    today_done = [
        o for o in _MOCK_DELIVERY_ORDERS
        if o.get("rider_id") == rider_id
        and o["status"] == "delivered"
        and o.get("delivered_at", "")[:10] == today
    ]

    return _ok({
        "rider_id": rider_id,
        "name": rider["name"],
        "phone": rider["phone"],
        "status": rider["status"],
        "current_orders": len(in_transit_orders),
        "today_completed": len(today_done) + rider.get("today_completed", 0),
        "in_transit_order_ids": [o["id"] for o in in_transit_orders],
    })


# ─── 9. 配送统计 ──────────────────────────────────────────────────────────────

@router.get("/stats", summary="配送统计（今日）")
async def get_delivery_stats() -> dict:
    """
    今日配送效率统计：
    - 派单数
    - 完成数
    - 平均配送时长（分钟）
    - 准时率（actual_minutes ≤ estimated_minutes）
    """
    today = _today_str()
    today_orders = [
        o for o in _MOCK_DELIVERY_ORDERS
        if o["created_at"][:10] == today
    ]

    dispatched_count = len(today_orders)
    completed = [o for o in today_orders if o["status"] == "delivered"]
    completed_count = len(completed)
    failed_count = len([o for o in today_orders if o["status"] == "failed"])
    pending_count = len([o for o in today_orders
                         if o["status"] in {"pending", "assigned", "picked_up", "delivering"}])

    # 平均配送时长
    valid_times = [o["actual_minutes"] for o in completed
                   if o.get("actual_minutes") is not None]
    avg_minutes = round(sum(valid_times) / len(valid_times), 1) if valid_times else 0.0

    # 准时率：actual_minutes ≤ estimated_minutes
    on_time = [
        o for o in completed
        if o.get("actual_minutes") is not None
        and o.get("estimated_minutes") is not None
        and o["actual_minutes"] <= o["estimated_minutes"]
    ]
    on_time_rate = (
        round(len(on_time) / completed_count * 100, 1) if completed_count > 0 else 0.0
    )

    return _ok({
        "date": today,
        "dispatched_count": dispatched_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "avg_delivery_minutes": avg_minutes,
        "on_time_rate_percent": on_time_rate,
        "rider_count_online": len([r for r in MOCK_RIDERS if r["status"] != "offline"]),
    })
