"""中央仓配送调度 -- 配送计划 / 路线优化 / 派车 / 签收 / 看板

配送状态: planned -> dispatched -> in_transit -> delivered
所有操作强制 tenant_id 租户隔离。
"""
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

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


# ─── 内部存储 ───


_plans: dict[str, dict] = {}          # plan_id -> 配送计划
_warehouses: dict[str, dict] = {}     # warehouse_id -> 仓库信息（含坐标）
_stores_geo: dict[str, dict] = {}     # store_id -> {lat, lng, store_name, address}
_drivers: dict[str, dict] = {}        # driver_id -> 司机信息


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())


# ─── 数据注入（供测试和外部服务调用） ───


def inject_warehouse(warehouse_id: str, tenant_id: str, data: dict) -> None:
    """注入仓库信息

    data: {warehouse_name, lat, lng, address, capacity}
    """
    key = f"{tenant_id}:{warehouse_id}"
    _warehouses[key] = {**data, "warehouse_id": warehouse_id, "tenant_id": tenant_id}


def inject_store_geo(store_id: str, tenant_id: str, data: dict) -> None:
    """注入门店地理信息

    data: {store_name, lat, lng, address}
    """
    key = f"{tenant_id}:{store_id}"
    _stores_geo[key] = {**data, "store_id": store_id, "tenant_id": tenant_id}


def inject_driver(driver_id: str, tenant_id: str, data: dict) -> None:
    """注入司机信息

    data: {driver_name, phone, vehicle_no, vehicle_type, capacity_kg}
    """
    key = f"{tenant_id}:{driver_id}"
    _drivers[key] = {**data, "driver_id": driver_id, "tenant_id": tenant_id}


# ─── 工具函数 ───


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


# ─── 核心服务函数 ───


def create_distribution_plan(
    warehouse_id: str,
    store_orders: list[dict],
    tenant_id: str,
    db: object = None,
) -> dict:
    """创建配送计划

    Args:
        warehouse_id: 中央仓 ID
        store_orders: 门店订货列表
            [{store_id, items: [{item_id, item_name, quantity, unit}]}]
        tenant_id: 租户 ID

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

    plan_id = _gen_id()
    now = _now_iso()

    store_deliveries = []
    total_items = 0

    for so in store_orders:
        store_id = so["store_id"]
        items = so.get("items", [])
        total_items += len(items)

        delivery = {
            "delivery_id": _gen_id(),
            "store_id": store_id,
            "items": [
                {
                    **item,
                    "status": DeliveryItemStatus.pending.value,
                }
                for item in items
            ],
            "status": DeliveryItemStatus.pending.value,
            "scheduled_at": None,
            "delivered_at": None,
        }
        store_deliveries.append(delivery)

    plan = {
        "plan_id": plan_id,
        "warehouse_id": warehouse_id,
        "tenant_id": tenant_id,
        "status": DistributionStatus.planned.value,
        "store_count": len(store_orders),
        "total_items": total_items,
        "store_deliveries": store_deliveries,
        "driver_id": None,
        "route": None,
        "created_at": now,
        "updated_at": now,
        "dispatched_at": None,
        "completed_at": None,
    }

    _plans[plan_id] = plan

    log.info(
        "distribution_plan_created",
        plan_id=plan_id,
        warehouse_id=warehouse_id,
        store_count=len(store_orders),
        total_items=total_items,
        tenant_id=tenant_id,
    )

    return plan


def optimize_route(
    plan_id: str,
    tenant_id: str,
    db: object = None,
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

    plan = _plans.get(plan_id)
    if not plan or plan["tenant_id"] != tenant_id:
        raise ValueError(f"配送计划不存在: {plan_id}")

    wh_key = f"{tenant_id}:{plan['warehouse_id']}"
    warehouse = _warehouses.get(wh_key)
    if not warehouse:
        log.warning("optimize_route_no_warehouse", plan_id=plan_id, tenant_id=tenant_id)
        return {
            "plan_id": plan_id,
            "optimized": False,
            "route": [],
            "total_distance_km": 0.0,
            "estimated_duration_min": 0.0,
        }

    wh_lat = warehouse.get("lat", 0.0)
    wh_lng = warehouse.get("lng", 0.0)

    # 收集门店坐标
    stores_to_visit = []
    for sd in plan["store_deliveries"]:
        sid = sd["store_id"]
        skey = f"{tenant_id}:{sid}"
        geo = _stores_geo.get(skey)
        if geo:
            stores_to_visit.append({
                "store_id": sid,
                "lat": geo.get("lat", 0.0),
                "lng": geo.get("lng", 0.0),
                "store_name": geo.get("store_name", ""),
            })
        else:
            stores_to_visit.append({
                "store_id": sid,
                "lat": wh_lat,
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
        current_lat, current_lng = nearest["lat"], nearest["lng"]
        unvisited.remove(nearest)
        seq += 1

    total_distance = round(cumulative_km, 2)
    # 估算时间：平均 30km/h 城市配送 + 每站 15 分钟装卸
    estimated_min = round(total_distance / 30 * 60 + len(route) * 15, 1)

    # 更新计划
    plan["route"] = route
    plan["updated_at"] = _now_iso()

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


def dispatch_delivery(
    plan_id: str,
    driver_id: str,
    tenant_id: str,
    db: object = None,
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

    plan = _plans.get(plan_id)
    if not plan or plan["tenant_id"] != tenant_id:
        raise ValueError(f"配送计划不存在: {plan_id}")

    if plan["status"] != DistributionStatus.planned.value:
        raise ValueError(
            f"只有 planned 状态可以派车，当前状态: {plan['status']}"
        )

    dkey = f"{tenant_id}:{driver_id}"
    driver = _drivers.get(dkey)

    now = _now_iso()
    plan["status"] = DistributionStatus.dispatched.value
    plan["driver_id"] = driver_id
    plan["dispatched_at"] = now
    plan["updated_at"] = now

    # 更新所有配送项状态
    for sd in plan["store_deliveries"]:
        for item in sd["items"]:
            item["status"] = DeliveryItemStatus.loaded.value

    log.info(
        "delivery_dispatched",
        plan_id=plan_id,
        driver_id=driver_id,
        tenant_id=tenant_id,
    )

    return {
        "plan_id": plan_id,
        "driver_id": driver_id,
        "driver_info": driver,
        "status": DistributionStatus.dispatched.value,
        "dispatched_at": now,
    }


def confirm_delivery(
    plan_id: str,
    store_id: str,
    received_items: list[dict],
    tenant_id: str,
    db: object = None,
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

    plan = _plans.get(plan_id)
    if not plan or plan["tenant_id"] != tenant_id:
        raise ValueError(f"配送计划不存在: {plan_id}")

    if plan["status"] not in (
        DistributionStatus.dispatched.value,
        DistributionStatus.in_transit.value,
    ):
        raise ValueError(
            f"只有 dispatched/in_transit 状态可以签收，当前: {plan['status']}"
        )

    # 更新为配送中（如果还是 dispatched）
    if plan["status"] == DistributionStatus.dispatched.value:
        plan["status"] = DistributionStatus.in_transit.value

    now = _now_iso()
    confirmed_items: list[dict] = []
    rejected_items: list[dict] = []

    # 找到该门店的配送记录
    target_delivery = None
    for sd in plan["store_deliveries"]:
        if sd["store_id"] == store_id:
            target_delivery = sd
            break

    if not target_delivery:
        raise ValueError(f"配送计划中未找到门店: {store_id}")

    received_map = {r["item_id"]: r for r in received_items}

    for item in target_delivery["items"]:
        iid = item.get("item_id")
        received = received_map.get(iid)
        if received:
            status = received.get("status", "accepted")
            if status == "rejected":
                item["status"] = DeliveryItemStatus.rejected.value
                rejected_items.append({
                    **item,
                    "reason": received.get("notes", ""),
                })
            elif status == "partial":
                item["status"] = DeliveryItemStatus.partial.value
                item["received_quantity"] = received.get("received_quantity", 0)
                confirmed_items.append(item)
            else:
                item["status"] = DeliveryItemStatus.delivered.value
                item["received_quantity"] = received.get("received_quantity", item.get("quantity", 0))
                confirmed_items.append(item)
        else:
            # 未在签收列表中的视为已签收
            item["status"] = DeliveryItemStatus.delivered.value
            confirmed_items.append(item)

    target_delivery["status"] = DeliveryItemStatus.delivered.value
    target_delivery["delivered_at"] = now

    # 检查所有门店是否都已签收
    all_delivered = all(
        sd.get("status") == DeliveryItemStatus.delivered.value
        for sd in plan["store_deliveries"]
    )
    if all_delivered:
        plan["status"] = DistributionStatus.delivered.value
        plan["completed_at"] = now

    plan["updated_at"] = now

    log.info(
        "delivery_confirmed",
        plan_id=plan_id,
        store_id=store_id,
        confirmed_count=len(confirmed_items),
        rejected_count=len(rejected_items),
        plan_status=plan["status"],
        tenant_id=tenant_id,
    )

    return {
        "plan_id": plan_id,
        "store_id": store_id,
        "confirmed_items": confirmed_items,
        "rejected_items": rejected_items,
        "plan_status": plan["status"],
        "confirmed_at": now,
    }


def get_distribution_dashboard(
    warehouse_id: str,
    tenant_id: str,
    db: object = None,
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

    # 收集该仓库的所有计划
    plans = [
        p for p in _plans.values()
        if p["tenant_id"] == tenant_id and p["warehouse_id"] == warehouse_id
    ]

    summary = {
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
        status = p["status"]
        summary[status] = summary.get(status, 0) + 1

        plan_summary = {
            "plan_id": p["plan_id"],
            "status": p["status"],
            "store_count": p["store_count"],
            "total_items": p["total_items"],
            "driver_id": p.get("driver_id"),
            "created_at": p["created_at"],
        }

        if p["created_at"] and today_str in p["created_at"]:
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


# ─── 测试工具 ───


def _clear_store() -> None:
    """清空内部存储，仅供测试用"""
    _plans.clear()
    _warehouses.clear()
    _stores_geo.clear()
    _drivers.clear()
