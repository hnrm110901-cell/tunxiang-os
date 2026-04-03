"""配送管理 Repository — 内存 → DB 迁移（v096）

覆盖 distribution.py 的四块内存存储：
  _plans       → distribution_plans（含 store_deliveries/route JSONB）
  _warehouses  → distribution_warehouses
  _stores_geo  → distribution_store_geos
  _drivers     → distribution_drivers

路线优化（Haversine 贪心算法）作为纯函数保留在本模块，不依赖 IO。
所有写方法调用 _set_tenant() 设置 RLS context。
"""
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─── 纯函数：Haversine 路线优化 ───────────────────────────────────────────


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine 公式计算两点距离（千米）"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _greedy_route(
    wh_lat: float,
    wh_lng: float,
    stores: list[dict],
) -> tuple[list[dict], float, float]:
    """贪心最近邻路线排序。

    Args:
        wh_lat/wh_lng: 仓库坐标
        stores: [{store_id, lat, lng, store_name}]

    Returns:
        (route, total_distance_km, estimated_duration_min)
    """
    route: list[dict] = []
    current_lat, current_lng = wh_lat, wh_lng
    unvisited = list(stores)
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
    # 城市配送估算：30km/h + 每站 15 分钟装卸
    estimated_min = round(total_distance / 30 * 60 + len(route) * 15, 1)
    return route, total_distance, estimated_min


# ─── Repository ───────────────────────────────────────────────────────────


class DistributionRepository:
    """配送管理数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 数据注入（仓库 / 门店地理 / 司机）
    # ══════════════════════════════════════════════════════

    async def upsert_warehouse(self, warehouse_id: str, data: dict) -> None:
        """注入/更新仓库信息（UPSERT）"""
        await self._set_tenant()
        await self.db.execute(
            text("""
                INSERT INTO distribution_warehouses
                    (id, tenant_id, warehouse_id, warehouse_name, lat, lng, address, capacity_kg, updated_at)
                VALUES
                    (:id, :tid, :wh_id, :name, :lat, :lng, :address, :capacity, NOW())
                ON CONFLICT (tenant_id, warehouse_id) DO UPDATE
                    SET warehouse_name = EXCLUDED.warehouse_name,
                        lat            = EXCLUDED.lat,
                        lng            = EXCLUDED.lng,
                        address        = EXCLUDED.address,
                        capacity_kg    = EXCLUDED.capacity_kg,
                        updated_at     = NOW()
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "wh_id": uuid.UUID(warehouse_id),
                "name": data.get("warehouse_name", ""),
                "lat": data.get("lat", 0.0),
                "lng": data.get("lng", 0.0),
                "address": data.get("address"),
                "capacity": data.get("capacity_kg"),
            },
        )
        await self.db.flush()

    async def upsert_store_geo(self, store_id: str, data: dict) -> None:
        """注入/更新门店地理信息（UPSERT）"""
        await self._set_tenant()
        await self.db.execute(
            text("""
                INSERT INTO distribution_store_geos
                    (id, tenant_id, store_id, store_name, lat, lng, address, updated_at)
                VALUES
                    (:id, :tid, :sid, :name, :lat, :lng, :address, NOW())
                ON CONFLICT (tenant_id, store_id) DO UPDATE
                    SET store_name = EXCLUDED.store_name,
                        lat        = EXCLUDED.lat,
                        lng        = EXCLUDED.lng,
                        address    = EXCLUDED.address,
                        updated_at = NOW()
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "sid": uuid.UUID(store_id),
                "name": data.get("store_name", ""),
                "lat": data.get("lat", 0.0),
                "lng": data.get("lng", 0.0),
                "address": data.get("address"),
            },
        )
        await self.db.flush()

    async def upsert_driver(self, driver_id: str, data: dict) -> None:
        """注入/更新司机信息（UPSERT）"""
        await self._set_tenant()
        await self.db.execute(
            text("""
                INSERT INTO distribution_drivers
                    (id, tenant_id, driver_id, driver_name, phone, vehicle_no,
                     vehicle_type, capacity_kg, updated_at)
                VALUES
                    (:id, :tid, :did, :name, :phone, :vehicle_no,
                     :vehicle_type, :capacity, NOW())
                ON CONFLICT (tenant_id, driver_id) DO UPDATE
                    SET driver_name  = EXCLUDED.driver_name,
                        phone        = EXCLUDED.phone,
                        vehicle_no   = EXCLUDED.vehicle_no,
                        vehicle_type = EXCLUDED.vehicle_type,
                        capacity_kg  = EXCLUDED.capacity_kg,
                        updated_at   = NOW()
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "did": uuid.UUID(driver_id),
                "name": data.get("driver_name", ""),
                "phone": data.get("phone"),
                "vehicle_no": data.get("vehicle_no"),
                "vehicle_type": data.get("vehicle_type"),
                "capacity": data.get("capacity_kg"),
            },
        )
        await self.db.flush()

    # ══════════════════════════════════════════════════════
    # 配送计划 CRUD
    # ══════════════════════════════════════════════════════

    async def create_plan(self, warehouse_id: str, store_orders: list[dict]) -> dict:
        """创建配送计划"""
        await self._set_tenant()
        plan_id = uuid.uuid4()

        store_deliveries = []
        total_items = 0
        for so in store_orders:
            items = so.get("items", [])
            total_items += len(items)
            store_deliveries.append({
                "delivery_id": str(uuid.uuid4()),
                "store_id": so["store_id"],
                "items": [{"status": "pending", **item} for item in items],
                "status": "pending",
                "scheduled_at": None,
                "delivered_at": None,
            })

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                INSERT INTO distribution_plans
                    (id, tenant_id, warehouse_id, status, store_count, total_items,
                     store_deliveries, created_at, updated_at)
                VALUES
                    (:id, :tid, :wh_id, 'planned', :store_count, :total_items,
                     :deliveries::jsonb, :now, :now)
            """),
            {
                "id": plan_id,
                "tid": self._tid,
                "wh_id": uuid.UUID(warehouse_id),
                "store_count": len(store_orders),
                "total_items": total_items,
                "deliveries": json.dumps(store_deliveries),
                "now": now,
            },
        )
        await self.db.flush()
        log.info("distribution_plan_created", plan_id=str(plan_id),
                 warehouse_id=warehouse_id, store_count=len(store_orders),
                 total_items=total_items, tenant_id=self.tenant_id)
        return await self._get_plan_or_raise(str(plan_id))

    async def get_plan(self, plan_id: str) -> Optional[dict]:
        """查询配送计划"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, warehouse_id, status, store_count, total_items,
                       driver_id, route, store_deliveries,
                       created_at, updated_at, dispatched_at, completed_at
                FROM distribution_plans
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            return None
        return self._plan_row_to_dict(row, plan_id)

    async def _get_plan_or_raise(self, plan_id: str) -> dict:
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"配送计划不存在: {plan_id}")
        return plan

    # ══════════════════════════════════════════════════════
    # 路线优化
    # ══════════════════════════════════════════════════════

    async def optimize_route(self, plan_id: str) -> dict:
        """路线优化（贪心最近邻）并将结果写入 DB"""
        await self._set_tenant()
        plan = await self._get_plan_or_raise(plan_id)

        warehouse_id = plan["warehouse_id"]
        wh_result = await self.db.execute(
            text("""
                SELECT lat, lng FROM distribution_warehouses
                WHERE warehouse_id = :wh_id AND tenant_id = :tid
            """),
            {"wh_id": uuid.UUID(warehouse_id), "tid": self._tid},
        )
        wh_row = wh_result.fetchone()
        if not wh_row:
            log.warning("optimize_route_no_warehouse", plan_id=plan_id, tenant_id=self.tenant_id)
            return {
                "plan_id": plan_id,
                "optimized": False,
                "route": [],
                "total_distance_km": 0.0,
                "estimated_duration_min": 0.0,
            }

        wh_lat, wh_lng = float(wh_row.lat), float(wh_row.lng)

        # 收集门店坐标
        store_ids = [sd["store_id"] for sd in plan["store_deliveries"]]
        if not store_ids:
            return {
                "plan_id": plan_id,
                "optimized": False,
                "route": [],
                "total_distance_km": 0.0,
                "estimated_duration_min": 0.0,
            }

        geo_result = await self.db.execute(
            text("""
                SELECT store_id, store_name, lat, lng
                FROM distribution_store_geos
                WHERE tenant_id = :tid AND store_id = ANY(:sids)
            """),
            {"tid": self._tid, "sids": [uuid.UUID(s) for s in store_ids]},
        )
        geo_map = {str(r.store_id): r for r in geo_result.fetchall()}

        stores_for_route = []
        for sid in store_ids:
            geo = geo_map.get(sid)
            stores_for_route.append({
                "store_id": sid,
                "lat": float(geo.lat) if geo else wh_lat,
                "lng": float(geo.lng) if geo else wh_lng,
                "store_name": geo.store_name if geo else "",
            })

        route, total_km, estimated_min = _greedy_route(wh_lat, wh_lng, stores_for_route)

        # 写入 DB
        await self.db.execute(
            text("""
                UPDATE distribution_plans
                SET route = :route::jsonb, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid
            """),
            {"route": json.dumps(route), "id": uuid.UUID(plan_id), "tid": self._tid},
        )
        await self.db.flush()

        log.info("route_optimized", plan_id=plan_id,
                 total_distance_km=total_km, store_count=len(route),
                 estimated_min=estimated_min, tenant_id=self.tenant_id)
        return {
            "plan_id": plan_id,
            "optimized": True,
            "route": route,
            "total_distance_km": total_km,
            "estimated_duration_min": estimated_min,
        }

    # ══════════════════════════════════════════════════════
    # 派车
    # ══════════════════════════════════════════════════════

    async def dispatch_delivery(self, plan_id: str, driver_id: str) -> dict:
        """派车：planned → dispatched，更新所有配送项为 loaded"""
        await self._set_tenant()
        plan = await self._get_plan_or_raise(plan_id)

        if plan["status"] != "planned":
            raise ValueError(f"只有 planned 状态可以派车，当前状态: {plan['status']}")

        # 更新 store_deliveries 中所有 item 状态为 loaded
        store_deliveries = plan["store_deliveries"]
        for sd in store_deliveries:
            for item in sd.get("items", []):
                item["status"] = "loaded"

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE distribution_plans
                SET status           = 'dispatched',
                    driver_id        = :driver_id,
                    store_deliveries = :deliveries::jsonb,
                    dispatched_at    = :now,
                    updated_at       = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "driver_id": uuid.UUID(driver_id),
                "deliveries": json.dumps(store_deliveries),
                "now": now,
                "id": uuid.UUID(plan_id),
                "tid": self._tid,
            },
        )
        await self.db.flush()

        # 查司机信息
        driver_result = await self.db.execute(
            text("""
                SELECT driver_name, phone, vehicle_no, vehicle_type, capacity_kg
                FROM distribution_drivers
                WHERE driver_id = :did AND tenant_id = :tid
            """),
            {"did": uuid.UUID(driver_id), "tid": self._tid},
        )
        driver_row = driver_result.fetchone()
        driver_info = (
            {
                "driver_name": driver_row.driver_name,
                "phone": driver_row.phone,
                "vehicle_no": driver_row.vehicle_no,
                "vehicle_type": driver_row.vehicle_type,
            }
            if driver_row else None
        )

        log.info("delivery_dispatched", plan_id=plan_id,
                 driver_id=driver_id, tenant_id=self.tenant_id)
        return {
            "plan_id": plan_id,
            "driver_id": driver_id,
            "driver_info": driver_info,
            "status": "dispatched",
            "dispatched_at": now.isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 门店签收
    # ══════════════════════════════════════════════════════

    async def confirm_delivery(
        self,
        plan_id: str,
        store_id: str,
        received_items: list[dict],
    ) -> dict:
        """门店签收，更新配送项状态，全部签收后完结计划"""
        await self._set_tenant()
        plan = await self._get_plan_or_raise(plan_id)

        if plan["status"] not in ("dispatched", "in_transit"):
            raise ValueError(
                f"只有 dispatched/in_transit 状态可以签收，当前: {plan['status']}"
            )

        store_deliveries = plan["store_deliveries"]
        target = next((sd for sd in store_deliveries if sd["store_id"] == store_id), None)
        if not target:
            raise ValueError(f"配送计划中未找到门店: {store_id}")

        now = datetime.now(timezone.utc)
        received_map = {r["item_id"]: r for r in received_items}
        confirmed_items: list[dict] = []
        rejected_items: list[dict] = []

        for item in target.get("items", []):
            iid = item.get("item_id")
            received = received_map.get(iid)
            if received:
                status = received.get("status", "accepted")
                if status == "rejected":
                    item["status"] = "rejected"
                    rejected_items.append({**item, "reason": received.get("notes", "")})
                elif status == "partial":
                    item["status"] = "partial"
                    item["received_quantity"] = received.get("received_quantity", 0)
                    confirmed_items.append(item)
                else:
                    item["status"] = "delivered"
                    item["received_quantity"] = received.get(
                        "received_quantity", item.get("quantity", 0)
                    )
                    confirmed_items.append(item)
            else:
                item["status"] = "delivered"
                confirmed_items.append(item)

        target["status"] = "delivered"
        target["delivered_at"] = now.isoformat()

        # 若所有门店都已签收，计划完结
        new_status = (
            "delivered"
            if all(sd.get("status") == "delivered" for sd in store_deliveries)
            else "in_transit"
        )
        completed_at = now if new_status == "delivered" else None

        await self.db.execute(
            text("""
                UPDATE distribution_plans
                SET status           = :status,
                    store_deliveries = :deliveries::jsonb,
                    completed_at     = :completed_at,
                    updated_at       = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "status": new_status,
                "deliveries": json.dumps(store_deliveries),
                "completed_at": completed_at,
                "now": now,
                "id": uuid.UUID(plan_id),
                "tid": self._tid,
            },
        )
        await self.db.flush()

        log.info("delivery_confirmed", plan_id=plan_id, store_id=store_id,
                 confirmed_count=len(confirmed_items), rejected_count=len(rejected_items),
                 plan_status=new_status, tenant_id=self.tenant_id)
        return {
            "plan_id": plan_id,
            "store_id": store_id,
            "confirmed_items": confirmed_items,
            "rejected_items": rejected_items,
            "plan_status": new_status,
            "confirmed_at": now.isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 配送看板
    # ══════════════════════════════════════════════════════

    async def get_dashboard(self, warehouse_id: str) -> dict:
        """配送看板：该仓库的统计 + 今日计划 + 活跃配送"""
        await self._set_tenant()
        wh_uuid = uuid.UUID(warehouse_id)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = await self.db.execute(
            text("""
                SELECT id, status, store_count, total_items, driver_id, created_at
                FROM distribution_plans
                WHERE tenant_id = :tid AND warehouse_id = :wh_id
                ORDER BY created_at DESC
                LIMIT 200
            """),
            {"tid": self._tid, "wh_id": wh_uuid},
        )
        rows = result.fetchall()

        summary: dict[str, int] = {
            "total_plans": 0,
            "planned": 0,
            "dispatched": 0,
            "in_transit": 0,
            "delivered": 0,
            "cancelled": 0,
        }
        today_plans: list[dict] = []
        active_deliveries: list[dict] = []

        for r in rows:
            summary["total_plans"] += 1
            status = r.status
            summary[status] = summary.get(status, 0) + 1

            plan_summary = {
                "plan_id": str(r.id),
                "status": status,
                "store_count": r.store_count,
                "total_items": r.total_items,
                "driver_id": str(r.driver_id) if r.driver_id else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }

            if r.created_at and r.created_at.strftime("%Y-%m-%d") == today_str:
                today_plans.append(plan_summary)

            if status in ("dispatched", "in_transit"):
                active_deliveries.append(plan_summary)

        total = summary["total_plans"]
        completion_rate = round(summary["delivered"] / total, 4) if total > 0 else 0.0

        log.info("distribution_dashboard_fetched", warehouse_id=warehouse_id,
                 total_plans=total, active=len(active_deliveries),
                 completion_rate=completion_rate, tenant_id=self.tenant_id)
        return {
            "warehouse_id": warehouse_id,
            "summary": summary,
            "today_plans": today_plans,
            "active_deliveries": active_deliveries,
            "completion_rate": completion_rate,
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _plan_row_to_dict(row, plan_id: str) -> dict:
        deliveries = row.store_deliveries
        if isinstance(deliveries, str):
            deliveries = json.loads(deliveries)
        route = row.route
        if isinstance(route, str):
            route = json.loads(route) if route else None

        return {
            "plan_id": plan_id,
            "warehouse_id": str(row.warehouse_id),
            "tenant_id": None,  # 不透传，由 RLS 保护
            "status": row.status,
            "store_count": row.store_count,
            "total_items": row.total_items,
            "driver_id": str(row.driver_id) if row.driver_id else None,
            "route": route,
            "store_deliveries": deliveries,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "dispatched_at": row.dispatched_at.isoformat() if row.dispatched_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
