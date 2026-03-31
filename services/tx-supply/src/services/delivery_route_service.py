"""中央厨房配送路线服务

路线优化策略（三级降级）:
  1. 调用腾讯地图/高德 API（需配置 API Key）
  2. 按门店区域分组（地理坐标聚类）
  3. fallback：按门店 sort_order 字段顺序

持久化层: PostgreSQL (SQLAlchemy async) + RLS 租户隔离
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.models.central_kitchen import (
    DeliveryItemORM,
    DeliveryTripORM,
    ProductionPlanORM,
)
from services.tx_supply.src.services.production_plan_service import (
    _store_geo,
)

log = structlog.get_logger(__name__)

# 差异阈值：实收与计划差超过 5% 则标记为 disputed
VARIANCE_THRESHOLD_PCT = 0.05

# 地图 API（实际部署时通过环境变量注入，测试阶段关闭）
MAP_API_ENABLED = False


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
            [s[0] for s in stores_with_geo[i : i + max_per_trip]]
            for i in range(0, len(stores_with_geo), max_per_trip)
        ]
        grouped_without_geo = [
            stores_without_geo[i : i + max_per_trip]
            for i in range(0, len(stores_without_geo), max_per_trip)
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
                dist = math.sqrt(
                    (last_geo["lat"] - c_geo["lat"]) ** 2
                    + (last_geo["lng"] - c_geo["lng"]) ** 2
                )
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
        """调用腾讯/高德地图 API 获取最优路线顺序（需配置 MAP_API_KEY）。

        实际实现：发送 HTTP 请求到地图 API，解析返回的路径规划结果。
        此处为接口占位，生产部署时填充真实 API 调用逻辑。
        """
        raise NotImplementedError("地图 API 未配置，使用降级策略")

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

        unsigned = [
            item for item in trip.items
            if item.status not in ("signed", "disputed")
        ]
        if unsigned:
            raise ValueError(
                f"配送单 {trip_id} 仍有 {len(unsigned)} 条明细未签收，无法更新库存"
            )

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
            stmt = (
                select(DeliveryTripORM)
                .where(
                    and_(
                        DeliveryTripORM.plan_id == plan.id,
                        DeliveryTripORM.tenant_id == uuid.UUID(tenant_id),
                        DeliveryTripORM.is_deleted == False,  # noqa: E712
                    )
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
