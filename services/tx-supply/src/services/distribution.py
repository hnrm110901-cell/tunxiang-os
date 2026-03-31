"""中央仓配送调度 -- 配送计划 / 路线优化 / 派车 / 签收 / 看板

配送状态: planned -> dispatched -> in_transit -> delivered
所有操作强制 tenant_id 租户隔离。

持久化: PostgreSQL + SQLAlchemy async
"""
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from sqlalchemy import select, func as sa_func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.models.distribution import (
    DistributionItem,
    DistributionPlan,
    DistributionTrip,
    DistributionWarehouse,
)

log = structlog.get_logger()


# ─── 配送状态 ───


class DistributionStatus(str, Enum):
    planned = "planned"           # 已计划
    dispatched = "dispatched"     # 已派车
    in_transit = "in_transit"     # 配送中
    delivered = "delivered"       # 已送达
    cancelled = "cancelled"       # 已取消


class DeliveryItemStatus(str, Enum):
    pending = "pending"
    loaded = "loaded"
    delivered = "delivered"
    rejected = "rejected"       # 门店拒收
    partial = "partial"         # 部分签收


# ─── 工具函数 ───


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _gen_id() -> uuid.UUID:
    return uuid.uuid4()


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine 公式计算两点距离（千米）"""
    R = 6371.0  # 地球半径 km
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


# ─── 数据注入（供测试和外部服务调用） ───


async def inject_warehouse(
    warehouse_id: str,
    tenant_id: str,
    data: dict,
    db: AsyncSession,
) -> None:
    """注入仓库信息

    data: {warehouse_name, lat, lng, address, capacity}
    """
    tid = uuid.UUID(tenant_id)
    wid = uuid.UUID(warehouse_id)
    wh = DistributionWarehouse(
        id=wid,
        tenant_id=tid,
        warehouse_name=data.get("warehouse_name", ""),
        lat=data.get("lat", 0.0),
        lng=data.get("lng", 0.0),
        address=data.get("address"),
        capacity=data.get("capacity"),
        contact_name=data.get("contact_name"),
        contact_phone=data.get("contact_phone"),
    )
    db.add(wh)
    await db.flush()


async def inject_store_geo(
    store_id: str,
    tenant_id: str,
    data: dict,
    db: AsyncSession,
) -> None:
    """注入门店地理信息 -- 门店表由 tx-org 管理，此处为兼容保留。

    实际路线优化从 stores 表读取坐标，此函数在测试中用于
    向内存 fallback 写入数据。生产环境应通过 stores 表管理。
    """
    # 门店 geo 由外部 stores 表管理，此处仅做 API 兼容
    pass


async def inject_driver(
    driver_id: str,
    tenant_id: str,
    data: dict,
    db: AsyncSession,
) -> None:
    """注入司机信息 -- 司机表由 tx-org 管理，此处为兼容保留。"""
    # 司机信息由外部 employees 表管理，此处仅做 API 兼容
    pass


# ─── 核心服务函数 ───


async def create_distribution_plan(
    warehouse_id: str,
    store_orders: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建配送计划

    Args:
        warehouse_id: 中央仓 ID
        store_orders: 门店订货列表
            [{store_id, items: [{item_id, item_name, quantity, unit}]}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {
            "plan_id": str,
            "warehouse_id": str,
            "status": "planned",
            "store_count": int,
            "total_items": int,
            "store_deliveries": [...],
            "created_at": str,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_orders:
        raise ValueError("store_orders 不能为空")

    tid = uuid.UUID(tenant_id)
    wid = uuid.UUID(warehouse_id)

    total_items = sum(len(so.get("items", [])) for so in store_orders)

    plan = DistributionPlan(
        tenant_id=tid,
        warehouse_id=wid,
        status=DistributionStatus.planned.value,
        store_count=len(store_orders),
        total_items=total_items,
    )
    db.add(plan)
    await db.flush()

    store_deliveries: list[dict] = []

    for so in store_orders:
        store_id = so["store_id"]
        items = so.get("items", [])

        trip = DistributionTrip(
            tenant_id=tid,
            plan_id=plan.id,
            store_id=uuid.UUID(store_id),
            status=DeliveryItemStatus.pending.value,
        )
        db.add(trip)
        await db.flush()

        trip_items: list[dict] = []
        for item in items:
            di = DistributionItem(
                tenant_id=tid,
                trip_id=trip.id,
                item_id=item.get("item_id", ""),
                item_name=item.get("item_name", ""),
                quantity=item.get("quantity", 0),
                unit=item.get("unit", ""),
                status=DeliveryItemStatus.pending.value,
            )
            db.add(di)
            await db.flush()
            trip_items.append({
                "item_id": di.item_id,
                "item_name": di.item_name,
                "quantity": float(di.quantity),
                "unit": di.unit,
                "status": di.status,
            })

        store_deliveries.append({
            "delivery_id": str(trip.id),
            "store_id": store_id,
            "items": trip_items,
            "status": trip.status,
            "scheduled_at": None,
            "delivered_at": None,
        })

    log.info(
        "distribution_plan_created",
        plan_id=str(plan.id),
        warehouse_id=warehouse_id,
        store_count=len(store_orders),
        total_items=total_items,
        tenant_id=tenant_id,
    )

    return {
        "plan_id": str(plan.id),
        "warehouse_id": warehouse_id,
        "tenant_id": tenant_id,
        "status": DistributionStatus.planned.value,
        "store_count": len(store_orders),
        "total_items": total_items,
        "store_deliveries": store_deliveries,
        "driver_id": None,
        "route": None,
        "created_at": plan.created_at.isoformat() if plan.created_at else _now_iso(),
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else _now_iso(),
        "dispatched_at": None,
        "completed_at": None,
    }


async def optimize_route(
    plan_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """路线优化（按门店距离排序 -- 贪心最近邻）

    从仓库出发，每次选择离当前位置最近的未访问门店。

    Returns:
        {
            "plan_id": str,
            "optimized": bool,
            "route": [{store_id, distance_km, cumulative_km, sequence}],
            "total_distance_km": float,
            "estimated_duration_min": float,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    tid = uuid.UUID(tenant_id)
    pid = uuid.UUID(plan_id)

    # 查询计划
    stmt = select(DistributionPlan).where(
        and_(
            DistributionPlan.id == pid,
            DistributionPlan.tenant_id == tid,
            DistributionPlan.is_deleted.is_(False),
        )
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"配送计划不存在: {plan_id}")

    # 查询仓库坐标
    wh_stmt = select(DistributionWarehouse).where(
        and_(
            DistributionWarehouse.id == plan.warehouse_id,
            DistributionWarehouse.tenant_id == tid,
            DistributionWarehouse.is_deleted.is_(False),
        )
    )
    wh_result = await db.execute(wh_stmt)
    warehouse = wh_result.scalar_one_or_none()
    if not warehouse:
        log.warning("optimize_route_no_warehouse", plan_id=plan_id, tenant_id=tenant_id)
        return {
            "plan_id": plan_id,
            "optimized": False,
            "route": [],
            "total_distance_km": 0.0,
            "estimated_duration_min": 0.0,
        }

    wh_lat = warehouse.lat or 0.0
    wh_lng = warehouse.lng or 0.0

    # 查询行程中的门店
    trips_stmt = select(DistributionTrip).where(
        and_(
            DistributionTrip.plan_id == pid,
            DistributionTrip.tenant_id == tid,
            DistributionTrip.is_deleted.is_(False),
        )
    )
    trips_result = await db.execute(trips_stmt)
    trips = list(trips_result.scalars().all())

    # 构建门店坐标列表（生产环境应 JOIN stores 表获取坐标，
    # 这里使用仓库坐标作 fallback）
    stores_to_visit: list[dict] = []
    for trip in trips:
        stores_to_visit.append({
            "store_id": str(trip.store_id),
            "trip_id": trip.id,
            "lat": wh_lat,  # TODO: JOIN stores 表获取实际坐标
            "lng": wh_lng,
            "store_name": "",
        })

    # 贪心最近邻排序
    route: list[dict] = []
    current_lat, current_lng = wh_lat, wh_lng
    unvisited = list(stores_to_visit)
    cumulative_km = 0.0
    seq = 1

    while unvisited:
        nearest = min(
            unvisited,
            key=lambda s: _haversine_distance(current_lat, current_lng, s["lat"], s["lng"]),
        )
        dist = _haversine_distance(current_lat, current_lng, nearest["lat"], nearest["lng"])
        cumulative_km += dist
        route.append({
            "store_id": nearest["store_id"],
            "store_name": nearest.get("store_name", ""),
            "distance_km": dist,
            "cumulative_km": round(cumulative_km, 2),
            "sequence": seq,
        })

        # 更新 trip 的 sequence
        trip_id = nearest["trip_id"]
        update_stmt = (
            update(DistributionTrip)
            .where(DistributionTrip.id == trip_id)
            .values(sequence=seq)
        )
        await db.execute(update_stmt)

        current_lat, current_lng = nearest["lat"], nearest["lng"]
        unvisited.remove(nearest)
        seq += 1

    total_distance = round(cumulative_km, 2)
    # 估算时间：平均 30km/h 城市配送 + 每站 15 分钟装卸
    estimated_min = round(total_distance / 30 * 60 + len(route) * 15, 1)

    # 更新计划的路线 JSON
    plan.route_json = route
    plan.updated_at = _now()
    await db.flush()

    log.info(
        "route_optimized",
        plan_id=plan_id,
        total_distance_km=total_distance,
        store_count=len(route),
        estimated_min=estimated_min,
        tenant_id=tenant_id,
    )

    return {
        "plan_id": plan_id,
        "optimized": True,
        "route": route,
        "total_distance_km": total_distance,
        "estimated_duration_min": estimated_min,
    }


async def dispatch_delivery(
    plan_id: str,
    driver_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """派车：planned -> dispatched

    Returns:
        {
            "plan_id": str,
            "driver_id": str,
            "driver_info": dict|None,
            "status": "dispatched",
            "dispatched_at": str,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    tid = uuid.UUID(tenant_id)
    pid = uuid.UUID(plan_id)

    stmt = select(DistributionPlan).where(
        and_(
            DistributionPlan.id == pid,
            DistributionPlan.tenant_id == tid,
            DistributionPlan.is_deleted.is_(False),
        )
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"配送计划不存在: {plan_id}")

    if plan.status != DistributionStatus.planned.value:
        raise ValueError(
            f"只有 planned 状态可以派车，当前状态: {plan.status}"
        )

    now = _now()
    plan.status = DistributionStatus.dispatched.value
    plan.driver_id = uuid.UUID(driver_id)
    plan.dispatched_at = now
    plan.updated_at = now

    # 更新所有配送项状态为 loaded
    items_stmt = (
        select(DistributionItem)
        .join(DistributionTrip, DistributionItem.trip_id == DistributionTrip.id)
        .where(
            and_(
                DistributionTrip.plan_id == pid,
                DistributionItem.tenant_id == tid,
                DistributionItem.is_deleted.is_(False),
            )
        )
    )
    items_result = await db.execute(items_stmt)
    for item in items_result.scalars().all():
        item.status = DeliveryItemStatus.loaded.value

    await db.flush()

    log.info(
        "delivery_dispatched",
        plan_id=plan_id,
        driver_id=driver_id,
        tenant_id=tenant_id,
    )

    return {
        "plan_id": plan_id,
        "driver_id": driver_id,
        "driver_info": None,
        "status": DistributionStatus.dispatched.value,
        "dispatched_at": now.isoformat(),
    }


async def confirm_delivery(
    plan_id: str,
    store_id: str,
    received_items: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """门店签收

    Args:
        received_items: [{item_id, received_quantity, status: "accepted"|"rejected"|"partial", notes}]

    Returns:
        {
            "plan_id": str,
            "store_id": str,
            "confirmed_items": [...],
            "rejected_items": [...],
            "plan_status": str,
            "confirmed_at": str,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    tid = uuid.UUID(tenant_id)
    pid = uuid.UUID(plan_id)
    sid = uuid.UUID(store_id)

    # 查询计划
    plan_stmt = select(DistributionPlan).where(
        and_(
            DistributionPlan.id == pid,
            DistributionPlan.tenant_id == tid,
            DistributionPlan.is_deleted.is_(False),
        )
    )
    plan_result = await db.execute(plan_stmt)
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"配送计划不存在: {plan_id}")

    if plan.status not in (
        DistributionStatus.dispatched.value,
        DistributionStatus.in_transit.value,
    ):
        raise ValueError(
            f"只有 dispatched/in_transit 状态可以签收，当前: {plan.status}"
        )

    # 更新为配送中
    if plan.status == DistributionStatus.dispatched.value:
        plan.status = DistributionStatus.in_transit.value

    now = _now()

    # 查找该门店的行程
    trip_stmt = select(DistributionTrip).where(
        and_(
            DistributionTrip.plan_id == pid,
            DistributionTrip.store_id == sid,
            DistributionTrip.tenant_id == tid,
            DistributionTrip.is_deleted.is_(False),
        )
    )
    trip_result = await db.execute(trip_stmt)
    target_trip = trip_result.scalar_one_or_none()
    if not target_trip:
        raise ValueError(f"配送计划中未找到门店: {store_id}")

    # 查找行程中的配送明细
    items_stmt = select(DistributionItem).where(
        and_(
            DistributionItem.trip_id == target_trip.id,
            DistributionItem.tenant_id == tid,
            DistributionItem.is_deleted.is_(False),
        )
    )
    items_result = await db.execute(items_stmt)
    db_items = list(items_result.scalars().all())

    received_map = {r["item_id"]: r for r in received_items}

    confirmed_items: list[dict] = []
    rejected_items: list[dict] = []

    for db_item in db_items:
        received = received_map.get(db_item.item_id)
        if received:
            status = received.get("status", "accepted")
            if status == "rejected":
                db_item.status = DeliveryItemStatus.rejected.value
                db_item.notes = received.get("notes", "")
                rejected_items.append({
                    "item_id": db_item.item_id,
                    "item_name": db_item.item_name,
                    "quantity": float(db_item.quantity),
                    "unit": db_item.unit,
                    "status": db_item.status,
                    "reason": received.get("notes", ""),
                })
            elif status == "partial":
                db_item.status = DeliveryItemStatus.partial.value
                db_item.received_quantity = received.get("received_quantity", 0)
                confirmed_items.append({
                    "item_id": db_item.item_id,
                    "item_name": db_item.item_name,
                    "quantity": float(db_item.quantity),
                    "received_quantity": float(db_item.received_quantity),
                    "unit": db_item.unit,
                    "status": db_item.status,
                })
            else:
                db_item.status = DeliveryItemStatus.delivered.value
                db_item.received_quantity = received.get(
                    "received_quantity", float(db_item.quantity),
                )
                confirmed_items.append({
                    "item_id": db_item.item_id,
                    "item_name": db_item.item_name,
                    "quantity": float(db_item.quantity),
                    "received_quantity": float(db_item.received_quantity),
                    "unit": db_item.unit,
                    "status": db_item.status,
                })
        else:
            # 未在签收列表中的视为已签收
            db_item.status = DeliveryItemStatus.delivered.value
            confirmed_items.append({
                "item_id": db_item.item_id,
                "item_name": db_item.item_name,
                "quantity": float(db_item.quantity),
                "unit": db_item.unit,
                "status": db_item.status,
            })

    target_trip.status = DeliveryItemStatus.delivered.value
    target_trip.delivered_at = now

    # 检查所有门店是否都已签收
    all_trips_stmt = select(DistributionTrip).where(
        and_(
            DistributionTrip.plan_id == pid,
            DistributionTrip.tenant_id == tid,
            DistributionTrip.is_deleted.is_(False),
        )
    )
    all_trips_result = await db.execute(all_trips_stmt)
    all_trips = list(all_trips_result.scalars().all())
    all_delivered = all(
        t.status == DeliveryItemStatus.delivered.value for t in all_trips
    )
    if all_delivered:
        plan.status = DistributionStatus.delivered.value
        plan.completed_at = now

    plan.updated_at = now
    await db.flush()

    log.info(
        "delivery_confirmed",
        plan_id=plan_id,
        store_id=store_id,
        confirmed_count=len(confirmed_items),
        rejected_count=len(rejected_items),
        plan_status=plan.status,
        tenant_id=tenant_id,
    )

    return {
        "plan_id": plan_id,
        "store_id": store_id,
        "confirmed_items": confirmed_items,
        "rejected_items": rejected_items,
        "plan_status": plan.status,
        "confirmed_at": now.isoformat(),
    }


async def get_distribution_dashboard(
    warehouse_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """配送看板

    Returns:
        {
            "warehouse_id": str,
            "summary": {
                "total_plans": int,
                "planned": int,
                "dispatched": int,
                "in_transit": int,
                "delivered": int,
                "cancelled": int,
            },
            "today_plans": [plan_summary],
            "active_deliveries": [plan_summary],
            "completion_rate": float,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    tid = uuid.UUID(tenant_id)
    wid = uuid.UUID(warehouse_id)

    # 查询该仓库的所有计划
    plans_stmt = select(DistributionPlan).where(
        and_(
            DistributionPlan.tenant_id == tid,
            DistributionPlan.warehouse_id == wid,
            DistributionPlan.is_deleted.is_(False),
        )
    )
    plans_result = await db.execute(plans_stmt)
    plans = list(plans_result.scalars().all())

    summary: dict[str, int] = {
        "total_plans": len(plans),
        "planned": 0,
        "dispatched": 0,
        "in_transit": 0,
        "delivered": 0,
        "cancelled": 0,
    }

    today_plans: list[dict] = []
    active_deliveries: list[dict] = []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for p in plans:
        status = p.status
        if status in summary:
            summary[status] += 1

        plan_summary = {
            "plan_id": str(p.id),
            "status": p.status,
            "store_count": p.store_count,
            "total_items": p.total_items,
            "driver_id": str(p.driver_id) if p.driver_id else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }

        if p.created_at and today_str in p.created_at.isoformat():
            today_plans.append(plan_summary)

        if status in (
            DistributionStatus.dispatched.value,
            DistributionStatus.in_transit.value,
        ):
            active_deliveries.append(plan_summary)

    total = summary["total_plans"]
    delivered = summary["delivered"]
    completion_rate = round(delivered / total, 4) if total > 0 else 0.0

    log.info(
        "distribution_dashboard_fetched",
        warehouse_id=warehouse_id,
        total_plans=total,
        active=len(active_deliveries),
        completion_rate=completion_rate,
        tenant_id=tenant_id,
    )

    return {
        "warehouse_id": warehouse_id,
        "summary": summary,
        "today_plans": today_plans,
        "active_deliveries": active_deliveries,
        "completion_rate": completion_rate,
    }
