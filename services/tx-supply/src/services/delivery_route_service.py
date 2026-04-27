"""中央厨房配送路线服务

路线优化策略（三级降级）:
  1. 调用腾讯地图/高德 API（需配置 API Key）
  2. 按门店区域分组（地理坐标聚类）
  3. fallback：按门店 sort_order 字段顺序

持久化层: PostgreSQL (SQLAlchemy async) + RLS 租户隔离
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from services.tx_supply.src.models.central_kitchen import (
    DeliveryItemORM,
    DeliveryTripORM,
    ProductionPlanORM,
)
from services.tx_supply.src.services.production_plan_service import (
    _store_geo,
)
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 差异阈值：实收与计划差超过 5% 则标记为 disputed
VARIANCE_THRESHOLD_PCT = 0.05

# 地图 API（实际部署时通过环境变量注入，测试阶段关闭）
# 设置 AMAP_API_KEY 环境变量即可启用高德路线规划
AMAP_API_KEY: Optional[str] = os.environ.get("AMAP_API_KEY")
MAP_API_ENABLED: bool = bool(AMAP_API_KEY)

# 高德路线规划 API 端点（驾车路径规划 v3）
_AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
# 地球半径（km）- 用于 Haversine 距离计算
_EARTH_RADIUS_KM = 6371.0

# ─── 轻量内存共享存储（用于路线/司机任务的临时状态，DB 迁移未覆盖的遗留路径） ───
_SHARED_STORE: Dict[str, Any] = {
    "trips": {},
    "now_iso": lambda: datetime.now(timezone.utc).isoformat(),
    "gen_id": lambda prefix: f"{prefix}_{uuid.uuid4().hex[:12]}",
}


def _shared() -> Dict[str, Any]:
    """返回进程内共享内存存储（trips / now_iso / gen_id）。"""
    return _SHARED_STORE


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """在当前 DB 连接上设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


class DeliveryRouteService:
    def _get_store_geo(self, store_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """获取门店地理信息"""
        return _store_geo.get(f"{tenant_id}:{store_id}")

    def cluster_stores_by_region(
        self,
        store_ids: List[str],
        tenant_id: str,
        max_per_trip: int = 6,
    ) -> List[List[str]]:
        """按门店区域分组（地理坐标聚类，简化版，每组最多 max_per_trip 个门店）。

        降级策略：无地理信息的门店按原始顺序分组。
        """
        stores_with_geo: List[tuple[str, float, float]] = []
        stores_without_geo: List[str] = []

        for store_id in store_ids:
            geo = self._get_store_geo(store_id, tenant_id)
            if geo and "lat" in geo and "lng" in geo:
                stores_with_geo.append((store_id, geo["lat"], geo["lng"]))
            else:
                log.warning(
                    "store_geo_missing",
                    store_id=store_id,
                    tenant_id=tenant_id,
                )
                stores_without_geo.append(store_id)

        # 按纬度排序分组（生产环境可替换为 sklearn KMeans）
        stores_with_geo.sort(key=lambda x: (round(x[1], 1), x[2]))
        grouped_with_geo = [
            [s[0] for s in stores_with_geo[i : i + max_per_trip]] for i in range(0, len(stores_with_geo), max_per_trip)
        ]
        grouped_without_geo = [
            stores_without_geo[i : i + max_per_trip] for i in range(0, len(stores_without_geo), max_per_trip)
        ]
        return grouped_with_geo + grouped_without_geo

    def build_route_sequence(
        self,
        store_ids: List[str],
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """构建路线序列（贪心最近邻算法）。

        降级策略：
          - 有地理信息：贪心最近邻（欧氏距离近似）
          - 无地理信息：按 store_ids 顺序（sort_order fallback）
        """
        if not store_ids:
            return []

        geo_map: Dict[str, Dict[str, Any]] = {}
        for store_id in store_ids:
            geo = self._get_store_geo(store_id, tenant_id)
            if geo:
                geo_map[store_id] = geo

        if len(geo_map) < 2:
            return [
                {
                    "store_id": s,
                    "sequence": i + 1,
                    "address": geo_map.get(s, {}).get("address", ""),
                    "lat": geo_map.get(s, {}).get("lat"),
                    "lng": geo_map.get(s, {}).get("lng"),
                }
                for i, s in enumerate(store_ids)
            ]

        # 贪心最近邻：从第一个门店出发
        unvisited = list(store_ids)
        route: List[str] = [unvisited.pop(0)]
        while unvisited:
            last = route[-1]
            last_geo = geo_map.get(last)
            if not last_geo:
                route.append(unvisited.pop(0))
                continue

            nearest: Optional[str] = None
            nearest_dist = float("inf")
            for candidate in unvisited:
                c_geo = geo_map.get(candidate)
                if not c_geo:
                    continue
                # 欧氏距离近似（中国境内短距离精度足够）
                dist = math.sqrt((last_geo["lat"] - c_geo["lat"]) ** 2 + (last_geo["lng"] - c_geo["lng"]) ** 2)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = candidate

            if nearest is None:
                nearest = unvisited[0]
            unvisited.remove(nearest)
            route.append(nearest)

        return [
            {
                "store_id": s,
                "sequence": i + 1,
                "address": geo_map.get(s, {}).get("address", ""),
                "lat": geo_map.get(s, {}).get("lat"),
                "lng": geo_map.get(s, {}).get("lng"),
            }
            for i, s in enumerate(route)
        ]

    async def optimize_route(
        self,
        trip_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """重新优化指定配送单的路线顺序。

        优先调用高德/腾讯 API；API 不可用时降级为地理聚类排序；
        无坐标数据时按 sort_order（原 route_sequence 顺序）。

        Raises:
            ValueError: 配送单不存在或租户不匹配
        """
        await _set_tenant(db, tenant_id)

        trip = await db.get(DeliveryTripORM, uuid.UUID(trip_id))
        if not trip or trip.is_deleted:
            raise ValueError(f"配送单 {trip_id} 不存在")
        if str(trip.tenant_id) != tenant_id:
            raise ValueError(f"配送单 {trip_id} 不属于当前租户")

        store_ids = [entry["store_id"] for entry in (trip.route_sequence or [])]
        if not store_ids:
            store_ids = list({str(item.store_id) for item in trip.items})

        log.info(
            "optimizing_route",
            trip_id=trip_id,
            store_count=len(store_ids),
            tenant_id=tenant_id,
        )

        if MAP_API_ENABLED:
            try:
                optimized_seq = await self._call_map_api(store_ids, tenant_id)
            except NotImplementedError:
                log.warning(
                    "map_api_not_implemented_fallback",
                    trip_id=trip_id,
                )
                optimized_seq = self.build_route_sequence(store_ids, tenant_id)
        else:
            optimized_seq = self.build_route_sequence(store_ids, tenant_id)

        trip.route_sequence = optimized_seq
        await db.flush()
        return {"trip_id": trip_id, "route_sequence": optimized_seq, "optimized": True}

    async def _call_map_api(
        self,
        store_ids: List[str],
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """调用高德地图路径规划 API 获取最优路线顺序。

        方案A（配置了 AMAP_API_KEY）：
          - 以第一个门店为起点，依次对剩余门店调用高德驾车路径规划 API
          - 用 Haversine 球面距离矩阵 + 贪心最近邻算法排序（避免 O(n!) 全排列）
          - 对每段路程调用高德 /v3/direction/driving 获取真实行驶时间/距离

        方案B（无 AMAP_API_KEY，自动 fallback 到贪心算法）：
          - 见 build_route_sequence()，基于欧氏距离近似

        Raises:
            RuntimeError: 高德 API 返回非 0 状态码时抛出，由 optimize_route() 捕获并降级
        """
        if not AMAP_API_KEY:
            raise NotImplementedError("AMAP_API_KEY 未配置，使用本地降级策略")

        # 收集有坐标的门店
        geo_map: Dict[str, Dict[str, Any]] = {}
        for store_id in store_ids:
            geo = self._get_store_geo(store_id, tenant_id)
            if geo and "lat" in geo and "lng" in geo:
                geo_map[store_id] = geo

        if len(geo_map) < 2:
            # 坐标不足，退回本地贪心
            return self.build_route_sequence(store_ids, tenant_id)

        # 用 Haversine 距离矩阵做贪心排序
        ordered = await self._greedy_route_with_amap(store_ids, geo_map, tenant_id)
        return ordered

    @staticmethod
    def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Haversine 球面距离（km），精度优于平面欧氏距离。"""
        d_lat = math.radians(lat2 - lat1)
        d_lng = math.radians(lng2 - lng1)
        a = (
            math.sin(d_lat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
        )
        return _EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def _greedy_route_with_amap(
        self,
        store_ids: List[str],
        geo_map: Dict[str, Dict[str, Any]],
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """贪心最近邻排序 + 高德 API 验证每段行驶距离。

        排序逻辑：使用 Haversine 距离快速确定访问顺序，
        然后对每条路段调用高德驾车规划获取真实距离/时间写入 route_info。

        若高德 API 单段请求失败，降级为 Haversine 估算距离，不中断整体流程。
        """
        try:
            import httpx
        except ImportError:
            log.warning("httpx_not_installed_fallback_greedy")
            return self.build_route_sequence(store_ids, tenant_id)

        # Step 1: Haversine 贪心排序
        unvisited = list(store_ids)
        route: List[str] = [unvisited.pop(0)]
        while unvisited:
            last = route[-1]
            last_geo = geo_map.get(last)
            if not last_geo:
                route.append(unvisited.pop(0))
                continue
            nearest: Optional[str] = None
            nearest_dist = float("inf")
            for candidate in unvisited:
                c_geo = geo_map.get(candidate)
                if not c_geo:
                    continue
                dist = self._haversine_km(
                    last_geo["lat"],
                    last_geo["lng"],
                    c_geo["lat"],
                    c_geo["lng"],
                )
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = candidate
            if nearest is None:
                nearest = unvisited[0]
            unvisited.remove(nearest)
            route.append(nearest)

        # Step 2: 对每段调用高德驾车路径规划，获取真实行驶时间/距离
        result: List[Dict[str, Any]] = []
        total_distance_m = 0
        total_duration_s = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for i, store_id in enumerate(route):
                geo = geo_map.get(store_id, {})
                segment_distance_m: Optional[int] = None
                segment_duration_s: Optional[int] = None

                if i > 0:
                    prev_geo = geo_map.get(route[i - 1], {})
                    if prev_geo and geo:
                        try:
                            params = {
                                "key": AMAP_API_KEY,
                                "origin": f"{prev_geo['lng']},{prev_geo['lat']}",
                                "destination": f"{geo['lng']},{geo['lat']}",
                                "strategy": 0,  # 最快路线
                                "output": "json",
                            }
                            resp = await client.get(_AMAP_DRIVING_URL, params=params)
                            resp.raise_for_status()
                            data = resp.json()

                            if data.get("status") == "1" and data.get("route", {}).get("paths"):
                                path = data["route"]["paths"][0]
                                segment_distance_m = int(path.get("distance", 0))
                                segment_duration_s = int(path.get("duration", 0))
                                total_distance_m += segment_distance_m
                                total_duration_s += segment_duration_s
                            else:
                                info = data.get("info", "unknown")
                                log.warning(
                                    "amap_api_segment_failed",
                                    from_store=route[i - 1],
                                    to_store=store_id,
                                    amap_info=info,
                                )
                                # fallback：Haversine 估算（1.4 迂回系数）
                                if prev_geo and geo:
                                    hav_km = self._haversine_km(
                                        prev_geo["lat"],
                                        prev_geo["lng"],
                                        geo["lat"],
                                        geo["lng"],
                                    )
                                    segment_distance_m = round(hav_km * 1400)
                        except (httpx.HTTPError, KeyError, ValueError) as exc:
                            log.warning(
                                "amap_api_request_failed",
                                to_store=store_id,
                                error=str(exc),
                            )

                result.append(
                    {
                        "store_id": store_id,
                        "sequence": i + 1,
                        "address": geo.get("address", ""),
                        "lat": geo.get("lat"),
                        "lng": geo.get("lng"),
                        "segment_distance_m": segment_distance_m,
                        "segment_duration_s": segment_duration_s,
                    }
                )

        log.info(
            "amap_route_planned",
            store_count=len(route),
            total_distance_km=round(total_distance_m / 1000, 2),
            total_duration_min=round(total_duration_s / 60, 1),
            tenant_id=tenant_id,
        )
        return result

    async def sign_receipt(
        self,
        delivery_item_id: str,
        actual_qty: float,
        operator_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """门店签收：记录实收量，差异超过 5% 时标记 disputed。

        Raises:
            ValueError: 配送明细不存在、租户不匹配或数量非法
        """
        await _set_tenant(db, tenant_id)

        item = await db.get(DeliveryItemORM, uuid.UUID(delivery_item_id))
        if not item or item.is_deleted:
            raise ValueError(f"配送明细 {delivery_item_id} 不存在")
        if str(item.tenant_id) != tenant_id:
            raise ValueError(f"配送明细 {delivery_item_id} 不属于当前租户")
        if actual_qty < 0:
            raise ValueError("实收量不能为负数")
        if item.status in ("signed", "disputed"):
            raise ValueError(f"配送明细 {delivery_item_id} 已签收，不能重复操作")

        planned = float(item.planned_qty)
        variance = actual_qty - planned
        variance_pct = abs(variance) / planned if planned > 0 else 0.0

        item.received_qty = actual_qty
        item.variance_qty = round(variance, 3)
        item.received_at = datetime.now(timezone.utc)

        if variance_pct > VARIANCE_THRESHOLD_PCT:
            item.status = "disputed"
            log.warning(
                "delivery_item_disputed",
                delivery_item_id=delivery_item_id,
                planned_qty=planned,
                actual_qty=actual_qty,
                variance_pct=round(variance_pct * 100, 2),
                operator_id=operator_id,
                tenant_id=tenant_id,
            )
        else:
            item.status = "signed"

        await db.flush()

        log.info(
            "delivery_item_signed",
            delivery_item_id=delivery_item_id,
            status=item.status,
            operator_id=operator_id,
            tenant_id=tenant_id,
        )
        return {
            "id": str(item.id),
            "tenant_id": str(item.tenant_id),
            "trip_id": str(item.trip_id),
            "store_id": str(item.store_id),
            "ingredient_id": str(item.ingredient_id),
            "planned_qty": planned,
            "received_qty": actual_qty,
            "variance_qty": round(variance, 3),
            "received_at": item.received_at.isoformat() if item.received_at else None,
            "status": item.status,
            "variance_pct": round(variance_pct * 100, 2),
            "operator_id": operator_id,
        }

    async def update_store_inventory(
        self,
        trip_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """签收完成后更新各门店库存（INSERT inventory_records）。

        要求：配送单下所有明细均已签收（signed 或 disputed）。

        Raises:
            ValueError: 配送单不存在、租户不匹配或仍有未签收明细
        """
        await _set_tenant(db, tenant_id)

        trip = await db.get(DeliveryTripORM, uuid.UUID(trip_id))
        if not trip or trip.is_deleted:
            raise ValueError(f"配送单 {trip_id} 不存在")
        if str(trip.tenant_id) != tenant_id:
            raise ValueError(f"配送单 {trip_id} 不属于当前租户")

        unsigned = [item for item in trip.items if item.status not in ("signed", "disputed")]
        if unsigned:
            raise ValueError(f"配送单 {trip_id} 仍有 {len(unsigned)} 条明细未签收，无法更新库存")

        inventory_records: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in trip.items:
            qty = float(item.received_qty) if item.received_qty is not None else 0.0
            record = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "store_id": str(item.store_id),
                "ingredient_id": str(item.ingredient_id),
                "quantity_change": qty,
                "direction": "in",
                "source": "central_kitchen_delivery",
                "source_ref_id": trip_id,
                "created_at": now_iso,
            }
            inventory_records.append(record)
            log.info(
                "inventory_record_created",
                store_id=str(item.store_id),
                ingredient_id=str(item.ingredient_id),
                qty=qty,
                tenant_id=tenant_id,
            )

        trip.status = "completed"

        # 检查计划下所有配送单是否全部完成
        plan = await db.get(ProductionPlanORM, trip.plan_id)
        if plan:
            stmt = select(DeliveryTripORM).where(
                and_(
                    DeliveryTripORM.plan_id == plan.id,
                    DeliveryTripORM.tenant_id == uuid.UUID(tenant_id),
                    DeliveryTripORM.is_deleted == False,  # noqa: E712
                )
            )
            result = await db.execute(stmt)
            plan_trips = result.scalars().all()
            if plan_trips and all(t.status == "completed" for t in plan_trips):
                plan.status = "completed"
                log.info(
                    "production_plan_completed",
                    plan_id=str(plan.id),
                    tenant_id=tenant_id,
                )

        await db.flush()

        return {
            "trip_id": trip_id,
            "trip_status": trip.status,
            "inventory_records_created": len(inventory_records),
            "records": inventory_records,
        }

    async def plan_route(
        self,
        kitchen_id: str,
        store_ids: List[str],
        tenant_id: str,
        plan_date: Optional[str] = None,
        db: Any = None,
    ) -> Dict[str, Any]:
        """中央厨房→多门店配送路线规划。

        方案A（配置了 AMAP_API_KEY）：调用高德路线规划 API，批量路径优化。
        方案B（无 AMAP_API_KEY，fallback）：贪心算法，从中央厨房出发，每次选最近未访问门店。
          门店坐标从 store_geo 共享存储读取（stores.longitude/latitude）。

        Args:
            kitchen_id:  中央厨房 ID（起点）
            store_ids:   目标门店 ID 列表
            tenant_id:   租户 ID
            plan_date:   配送日期（ISO 格式，可选）
            db:          数据库会话（预留，当前内存实现不使用）

        Returns:
            DeliveryRoute dict，包含 route_id / kitchen_id / route_sequence /
            total_distance_km / planned_date / algorithm_used
        """
        if not store_ids:
            raise ValueError("门店列表不能为空")

        store = _shared()  # noqa: F821  # TODO(P1): _shared 未在本模块定义，生产调用会 NameError；需补充内存状态工厂
        gen_id = store["gen_id"]
        now_iso = store["now_iso"]

        route_id = gen_id("route")

        log.info(
            "plan_route.start",
            kitchen_id=kitchen_id,
            store_count=len(store_ids),
            map_api_enabled=MAP_API_ENABLED,
            tenant_id=tenant_id,
        )

        algorithm_used = "amap_api" if MAP_API_ENABLED else "greedy_haversine"

        if MAP_API_ENABLED:
            try:
                route_sequence = await self._call_map_api(store_ids, tenant_id)
            except (NotImplementedError, Exception) as exc:
                log.warning(
                    "plan_route.map_api_fallback",
                    error=str(exc),
                    tenant_id=tenant_id,
                )
                route_sequence = self.build_route_sequence(store_ids, tenant_id)
                algorithm_used = "greedy_haversine_fallback"
        else:
            route_sequence = self.build_route_sequence(store_ids, tenant_id)

        # 估算总距离（如果 route_sequence 包含 segment_distance_m 则使用真实值）
        total_distance_m = sum(s.get("segment_distance_m") or 0 for s in route_sequence)
        if total_distance_m == 0:
            # fallback：Haversine 累加估算
            geo_map: Dict[str, Dict[str, Any]] = {}
            for sid in store_ids:
                geo = self._get_store_geo(sid, tenant_id)
                if geo:
                    geo_map[sid] = geo
            for i in range(1, len(route_sequence)):
                prev_geo = geo_map.get(route_sequence[i - 1]["store_id"], {})
                curr_geo = geo_map.get(route_sequence[i]["store_id"], {})
                if prev_geo and curr_geo:
                    total_distance_m += round(
                        self._haversine_km(
                            prev_geo["lat"],
                            prev_geo["lng"],
                            curr_geo["lat"],
                            curr_geo["lng"],
                        )
                        * 1000
                    )

        route = {
            "route_id": route_id,
            "kitchen_id": kitchen_id,
            "tenant_id": tenant_id,
            "store_ids": store_ids,
            "route_sequence": route_sequence,
            "total_distance_km": round(total_distance_m / 1000, 2),
            "algorithm_used": algorithm_used,
            "planned_date": plan_date or now_iso()[:10],
            "status": "planned",
            "created_at": now_iso(),
        }

        # 存入共享 trips 便于后续 get_driver_task / update_delivery_progress 读取
        _shared()["trips"][route_id] = {  # noqa: F821  # TODO(P1): _shared 未定义
            **route,
            "plan_id": kitchen_id,  # 使用 kitchen_id 作为 plan_id 占位
            "items": [],
        }

        log.info(
            "plan_route.done",
            route_id=route_id,
            total_distance_km=route["total_distance_km"],
            algorithm=algorithm_used,
            tenant_id=tenant_id,
        )
        return route

    async def get_driver_task(
        self,
        route_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """司机工作任务单：按顺序显示每个门店的配送内容。

        Returns:
            {route_id, driver_task: [{sequence, store_id, address, items, status}], ...}

        Raises:
            ValueError: 路线不存在或租户不匹配
        """
        trips = _shared()["trips"]  # noqa: F821  # TODO(P1): _shared 未定义
        trip = trips.get(route_id)
        if not trip:
            raise ValueError(f"配送路线 {route_id} 不存在")
        if trip.get("tenant_id") != tenant_id:
            raise ValueError(f"配送路线 {route_id} 不属于当前租户")

        # 按 store_id 分组配送明细
        items_by_store: Dict[str, List[Dict[str, Any]]] = {}
        for item in trip.get("items", []):
            sid = item.get("store_id", "")
            items_by_store.setdefault(sid, []).append(
                {
                    "ingredient_id": item.get("ingredient_id"),
                    "ingredient_name": item.get("ingredient_name", ""),
                    "planned_qty": item.get("planned_qty"),
                    "unit": item.get("unit", "kg"),
                    "status": item.get("status", "pending"),
                }
            )

        route_sequence = trip.get("route_sequence", [])
        driver_task = []
        for stop in route_sequence:
            sid = stop["store_id"]
            driver_task.append(
                {
                    "sequence": stop["sequence"],
                    "store_id": sid,
                    "address": stop.get("address", ""),
                    "lat": stop.get("lat"),
                    "lng": stop.get("lng"),
                    "items": items_by_store.get(sid, []),
                    "delivery_status": trip.get(f"_stop_status_{sid}", "pending"),
                    "segment_distance_m": stop.get("segment_distance_m"),
                    "segment_duration_s": stop.get("segment_duration_s"),
                }
            )

        log.info(
            "get_driver_task",
            route_id=route_id,
            stop_count=len(driver_task),
            tenant_id=tenant_id,
        )
        return {
            "route_id": route_id,
            "kitchen_id": trip.get("kitchen_id"),
            "planned_date": trip.get("planned_date"),
            "total_distance_km": trip.get("total_distance_km"),
            "algorithm_used": trip.get("algorithm_used"),
            "driver_task": driver_task,
            "overall_status": trip.get("status", "planned"),
        }

    async def update_delivery_progress(
        self,
        route_id: str,
        store_id: str,
        status: str,
        tenant_id: str,
        operator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """实时更新配送进度（departed / arrived / delivered）。

        Args:
            route_id:    配送路线 ID
            store_id:    本次更新的门店 ID
            status:      新状态：departed（已出发）/ arrived（已到达）/ delivered（已送达）
            tenant_id:   租户 ID
            operator_id: 操作人（可选）

        Returns:
            更新后的该门店配送状态快照

        Raises:
            ValueError: 路线/门店不存在，状态值非法，或租户不匹配
        """
        _valid_statuses = {"departed", "arrived", "delivered"}
        if status not in _valid_statuses:
            raise ValueError(f"状态无效: {status}，必须是 {_valid_statuses} 之一")

        trips = _shared()["trips"]  # noqa: F821  # TODO(P1): _shared 未定义
        now_iso = _shared()["now_iso"]  # noqa: F821  # TODO(P1): _shared 未定义

        trip = trips.get(route_id)
        if not trip:
            raise ValueError(f"配送路线 {route_id} 不存在")
        if trip.get("tenant_id") != tenant_id:
            raise ValueError(f"配送路线 {route_id} 不属于当前租户")

        # 检查该门店是否在路线中
        route_store_ids = {s["store_id"] for s in trip.get("route_sequence", [])}
        if store_id not in route_store_ids:
            raise ValueError(f"门店 {store_id} 不在配送路线 {route_id} 中")

        now = now_iso()
        status_key = f"_stop_status_{store_id}"
        timestamp_key = f"_stop_ts_{store_id}"

        trip[status_key] = status
        trip[timestamp_key] = now

        # 若所有门店均为 delivered，自动标记路线完成
        all_delivered = all(
            trip.get(f"_stop_status_{s['store_id']}") == "delivered" for s in trip.get("route_sequence", [])
        )
        if all_delivered:
            trip["status"] = "completed"
            log.info("delivery_route_completed", route_id=route_id, tenant_id=tenant_id)
        elif status == "departed" and trip.get("status") == "planned":
            trip["status"] = "in_progress"

        log.info(
            "delivery_progress_updated",
            route_id=route_id,
            store_id=store_id,
            status=status,
            operator_id=operator_id,
            tenant_id=tenant_id,
        )
        return {
            "route_id": route_id,
            "store_id": store_id,
            "status": status,
            "updated_at": now,
            "route_status": trip["status"],
            "operator_id": operator_id,
        }
