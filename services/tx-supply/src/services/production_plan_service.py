"""中央厨房生产计划服务

流程: 需求汇总 -> 生产任务 -> 产能检查 -> 生产执行 -> 配送任务生成

持久化层: PostgreSQL (SQLAlchemy async) + RLS 租户隔离
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, text, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.models.central_kitchen import (
    DeliveryItemORM,
    DeliveryTripORM,
    ProductionPlanORM,
    ProductionTaskORM,
)

log = structlog.get_logger(__name__)

# 中央厨房产能上限（单位：kg / 天，可由环境变量或配置表覆盖）
DEFAULT_KITCHEN_CAPACITY_KG = 5000.0

# 档口分配规则（原料类型 -> 加工档口）
STATION_MAPPING: Dict[str, str] = {
    "meat": "档口A-肉类加工",
    "vegetable": "档口B-蔬菜清洗",
    "seafood": "档口C-海鲜处理",
    "grain": "档口D-主食加工",
    "sauce": "档口E-调料配制",
    "default": "档口F-综合加工",
}

# ─── 门店需求注入（生产环境替换为 requisitions 表查询） ───
_store_demands: Dict[str, List[Dict[str, Any]]] = {}
_store_geo: Dict[str, Dict[str, Any]] = {}


def inject_store_demand(store_id: str, tenant_id: str, demands: List[Dict[str, Any]]) -> None:
    """注入门店需求（测试用 / 生产环境由 requisitions 表替代）"""
    _store_demands[f"{tenant_id}:{store_id}"] = demands


def inject_store_geo(store_id: str, tenant_id: str, geo: Dict[str, Any]) -> None:
    """注入门店地理信息（测试用）"""
    _store_geo[f"{tenant_id}:{store_id}"] = geo


def _clear_store() -> None:
    """测试辅助：清空注入数据"""
    _store_demands.clear()
    _store_geo.clear()


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """在当前 DB 连接上设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _get_store_demands(store_ids: List[str], plan_date: str, tenant_id: str) -> List[Dict[str, Any]]:
    """汇总各门店对 plan_date 的原料需求（生产环境查询 requisitions + 历史均值预测）"""
    demands: List[Dict[str, Any]] = []
    for store_id in store_ids:
        key = f"{tenant_id}:{store_id}"
        store_demands_list = _store_demands.get(key, [])
        for d in store_demands_list:
            demands.append({**d, "store_id": store_id})
    return demands


def _aggregate_demands(demands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 ingredient_id 汇总需求量"""
    agg: Dict[str, Dict[str, Any]] = {}
    for d in demands:
        ing_id = d["ingredient_id"]
        if ing_id not in agg:
            agg[ing_id] = {
                "ingredient_id": ing_id,
                "ingredient_name": d.get("ingredient_name", ""),
                "total_qty": 0.0,
                "unit": d.get("unit", "kg"),
                "category": d.get("category", "default"),
                "store_ids": [],
            }
        agg[ing_id]["total_qty"] += float(d.get("quantity", 0))
        store_id = d.get("store_id")
        if store_id and store_id not in agg[ing_id]["store_ids"]:
            agg[ing_id]["store_ids"].append(store_id)
    return list(agg.values())


def _check_capacity(aggregated: List[Dict[str, Any]], capacity_kg: float) -> bool:
    """检查总需求是否超出中央厨房产能上限"""
    total_kg = sum(item["total_qty"] for item in aggregated)
    return total_kg <= capacity_kg


def plan_date_short(plan_date: str) -> str:
    """将 YYYY-MM-DD 转为 YYMMDD"""
    return plan_date.replace("-", "")[2:]


def _plan_to_dict(plan: ProductionPlanORM) -> Dict[str, Any]:
    """将 ORM Plan 转为 API 响应字典"""
    return {
        "id": str(plan.id),
        "tenant_id": str(plan.tenant_id),
        "kitchen_id": str(plan.kitchen_id),
        "plan_date": plan.plan_date.isoformat() if hasattr(plan.plan_date, "isoformat") else str(plan.plan_date),
        "status": plan.status,
        "total_items": plan.total_items,
        "created_by": str(plan.created_by) if plan.created_by else None,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "tasks": [_task_to_dict(t) for t in (plan.tasks or [])],
    }


def _task_to_dict(task: ProductionTaskORM) -> Dict[str, Any]:
    """将 ORM Task 转为 API 响应字典"""
    return {
        "id": str(task.id),
        "tenant_id": str(task.tenant_id),
        "plan_id": str(task.plan_id),
        "ingredient_id": str(task.ingredient_id),
        "planned_qty": float(task.planned_qty),
        "unit": task.unit,
        "assigned_station": task.assigned_station,
        "status": task.status,
        "actual_qty": float(task.actual_qty) if task.actual_qty is not None else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _trip_to_dict(trip: DeliveryTripORM) -> Dict[str, Any]:
    """将 ORM Trip 转为 API 响应字典"""
    return {
        "id": str(trip.id),
        "tenant_id": str(trip.tenant_id),
        "plan_id": str(trip.plan_id),
        "trip_no": trip.trip_no,
        "driver_name": trip.driver_name,
        "vehicle_plate": trip.vehicle_plate,
        "departure_time": trip.departure_time.isoformat() if trip.departure_time else None,
        "status": trip.status,
        "route_sequence": trip.route_sequence or [],
        "created_at": trip.created_at.isoformat() if trip.created_at else None,
        "items": [_item_to_dict(i) for i in (trip.items or [])],
    }


def _item_to_dict(item: DeliveryItemORM) -> Dict[str, Any]:
    """将 ORM DeliveryItem 转为 API 响应字典"""
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "trip_id": str(item.trip_id),
        "store_id": str(item.store_id),
        "ingredient_id": str(item.ingredient_id),
        "planned_qty": float(item.planned_qty),
        "received_qty": float(item.received_qty) if item.received_qty is not None else None,
        "variance_qty": float(item.variance_qty) if item.variance_qty is not None else None,
        "received_at": item.received_at.isoformat() if item.received_at else None,
        "status": item.status,
    }


class ProductionPlanService:

    async def generate_plan(
        self,
        kitchen_id: str,
        plan_date: str,
        tenant_id: str,
        store_ids: List[str],
        db: AsyncSession,
        created_by: Optional[str] = None,
        capacity_kg: float = DEFAULT_KITCHEN_CAPACITY_KG,
    ) -> Dict[str, Any]:
        """根据各门店次日需求量生成生产计划。

        Args:
            kitchen_id: 中央厨房 ID
            plan_date: 生产日期（YYYY-MM-DD）
            tenant_id: 租户 ID
            store_ids: 参与汇总的门店 ID 列表
            db: 数据库 async session
            created_by: 操作人 ID
            capacity_kg: 中央厨房当日产能上限（kg）

        Returns:
            生产计划字典

        Raises:
            ValueError: 参数校验失败或产能超限
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not kitchen_id:
            raise ValueError("kitchen_id 不能为空")
        if not plan_date:
            raise ValueError("plan_date 不能为空")
        if not store_ids:
            raise ValueError("store_ids 不能为空，至少需要一个门店")

        await _set_tenant(db, tenant_id)

        log.info(
            "generating_production_plan",
            kitchen_id=kitchen_id,
            plan_date=plan_date,
            tenant_id=tenant_id,
            store_count=len(store_ids),
        )

        # 1. 汇总各门店需求
        raw_demands = _get_store_demands(store_ids, plan_date, tenant_id)
        aggregated = _aggregate_demands(raw_demands)

        # 2. 产能检查
        if not _check_capacity(aggregated, capacity_kg):
            total_kg = sum(item["total_qty"] for item in aggregated)
            log.warning(
                "production_capacity_exceeded",
                total_kg=total_kg,
                capacity_kg=capacity_kg,
                tenant_id=tenant_id,
            )
            raise ValueError(
                f"需求总量 {total_kg:.1f} kg 超出中央厨房产能上限 {capacity_kg:.1f} kg"
            )

        # 3. 创建生产计划
        tenant_uuid = uuid.UUID(tenant_id)
        kitchen_uuid = uuid.UUID(kitchen_id)
        created_by_uuid = uuid.UUID(created_by) if created_by else None

        plan = ProductionPlanORM(
            tenant_id=tenant_uuid,
            kitchen_id=kitchen_uuid,
            plan_date=datetime.strptime(plan_date, "%Y-%m-%d").date(),
            status="draft",
            total_items=len(aggregated),
            created_by=created_by_uuid,
        )
        db.add(plan)
        await db.flush()  # 获取 plan.id

        # 4. 按加工工艺分组，生成 ProductionTask 列表
        for agg_item in aggregated:
            category = agg_item.get("category", "default")
            station = STATION_MAPPING.get(category, STATION_MAPPING["default"])
            task = ProductionTaskORM(
                tenant_id=tenant_uuid,
                plan_id=plan.id,
                ingredient_id=uuid.UUID(agg_item["ingredient_id"]),
                planned_qty=agg_item["total_qty"],
                unit=agg_item["unit"],
                assigned_station=station,
                status="pending",
            )
            db.add(task)

        await db.flush()
        await db.refresh(plan)

        log.info(
            "production_plan_generated",
            plan_id=str(plan.id),
            task_count=len(plan.tasks),
            tenant_id=tenant_id,
        )
        return _plan_to_dict(plan)

    async def list_plans(
        self,
        kitchen_id: str,
        plan_date: Optional[str],
        tenant_id: str,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """查询生产计划列表（按 kitchen_id 和可选日期过滤）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        await _set_tenant(db, tenant_id)

        tenant_uuid = uuid.UUID(tenant_id)
        kitchen_uuid = uuid.UUID(kitchen_id)

        stmt = (
            select(ProductionPlanORM)
            .where(
                and_(
                    ProductionPlanORM.tenant_id == tenant_uuid,
                    ProductionPlanORM.kitchen_id == kitchen_uuid,
                    ProductionPlanORM.is_deleted == False,  # noqa: E712
                )
            )
        )
        if plan_date:
            stmt = stmt.where(
                ProductionPlanORM.plan_date == datetime.strptime(plan_date, "%Y-%m-%d").date()
            )

        result = await db.execute(stmt)
        plans = result.scalars().all()
        return [_plan_to_dict(p) for p in plans]

    async def confirm_plan(
        self,
        plan_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """确认计划，锁定生产任务。

        Raises:
            ValueError: 计划不存在、租户不匹配或状态不允许确认
        """
        await _set_tenant(db, tenant_id)

        plan = await db.get(ProductionPlanORM, uuid.UUID(plan_id))
        if not plan or plan.is_deleted:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if str(plan.tenant_id) != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        if plan.status != "draft":
            raise ValueError(f"计划状态为 {plan.status}，只有 draft 状态可以确认")

        plan.status = "confirmed"
        await db.flush()
        await db.refresh(plan)

        log.info("production_plan_confirmed", plan_id=plan_id, tenant_id=tenant_id)
        return _plan_to_dict(plan)

    async def complete_task(
        self,
        task_id: str,
        actual_qty: float,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """加工完成，记录实际产量。

        Raises:
            ValueError: 任务不存在、租户不匹配或数量非法
        """
        await _set_tenant(db, tenant_id)

        task = await db.get(ProductionTaskORM, uuid.UUID(task_id))
        if not task or task.is_deleted:
            raise ValueError(f"生产任务 {task_id} 不存在")
        if str(task.tenant_id) != tenant_id:
            raise ValueError(f"生产任务 {task_id} 不属于当前租户")
        if actual_qty < 0:
            raise ValueError("实际产量不能为负数")
        if task.status == "done":
            raise ValueError(f"生产任务 {task_id} 已完成，不能重复提交")

        now = datetime.now(timezone.utc)
        if task.status == "pending":
            task.started_at = now
        task.status = "done"
        task.actual_qty = actual_qty
        task.completed_at = now

        # 检查计划下所有任务是否都已完成
        plan = await db.get(ProductionPlanORM, task.plan_id)
        if plan:
            all_done = all(t.status == "done" for t in plan.tasks)
            if all_done and plan.status == "confirmed":
                plan.status = "in_progress"
                log.info(
                    "all_tasks_done_plan_in_progress",
                    plan_id=str(plan.id),
                    tenant_id=tenant_id,
                )

        await db.flush()

        log.info(
            "production_task_completed",
            task_id=task_id,
            actual_qty=actual_qty,
            tenant_id=tenant_id,
        )
        return _task_to_dict(task)

    async def generate_delivery_trips(
        self,
        plan_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """生产完成后生成配送任务（按门店地理位置聚类优化路线）。

        Raises:
            ValueError: 计划不存在、租户不匹配或需求数据缺失
        """
        await _set_tenant(db, tenant_id)

        plan = await db.get(ProductionPlanORM, uuid.UUID(plan_id))
        if not plan or plan.is_deleted:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if str(plan.tenant_id) != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        if plan.status not in ("in_progress", "confirmed"):
            raise ValueError(
                f"计划状态为 {plan.status}，需要 confirmed 或 in_progress 才能生成配送任务"
            )

        # 收集各门店对应的配送明细
        store_item_map: Dict[str, List[Dict[str, Any]]] = {}
        for task in plan.tasks:
            for key, demands in _store_demands.items():
                key_tenant, store_id = key.split(":", 1)
                if key_tenant != tenant_id:
                    continue
                for d in demands:
                    if d["ingredient_id"] == str(task.ingredient_id):
                        if store_id not in store_item_map:
                            store_item_map[store_id] = []
                        store_item_map[store_id].append({
                            "ingredient_id": str(task.ingredient_id),
                            "planned_qty": float(d.get("quantity", 0)),
                            "unit": task.unit,
                        })

        if not store_item_map:
            raise ValueError("未找到任何门店配送需求，请先注入门店需求数据")

        # 按地理位置聚类分组
        route_svc = _DeliveryRouteHelper()
        store_groups = route_svc.cluster_stores_by_region(
            list(store_item_map.keys()), tenant_id
        )

        tenant_uuid = uuid.UUID(tenant_id)
        plan_uuid = uuid.UUID(plan_id)
        plan_date_str = plan.plan_date.isoformat() if hasattr(plan.plan_date, "isoformat") else str(plan.plan_date)

        trips: List[DeliveryTripORM] = []
        trip_counter = 1
        for group in store_groups:
            trip_no = f"TRP-{plan_date_short(plan_date_str)}-{trip_counter:02d}"

            # 路线排序
            route_seq = route_svc.build_route_sequence(group, tenant_id)

            trip = DeliveryTripORM(
                tenant_id=tenant_uuid,
                plan_id=plan_uuid,
                trip_no=trip_no,
                status="pending",
                route_sequence=route_seq,
            )
            db.add(trip)
            await db.flush()  # 获取 trip.id

            # 生成配送明细
            for seq_entry in route_seq:
                store_id = seq_entry["store_id"]
                for ing_item in store_item_map.get(store_id, []):
                    d_item = DeliveryItemORM(
                        tenant_id=tenant_uuid,
                        trip_id=trip.id,
                        store_id=uuid.UUID(store_id),
                        ingredient_id=uuid.UUID(ing_item["ingredient_id"]),
                        planned_qty=ing_item["planned_qty"],
                        status="pending",
                    )
                    db.add(d_item)

            trips.append(trip)
            trip_counter += 1

        # 更新计划状态
        plan.status = "in_progress"
        await db.flush()

        # refresh trips to load items
        for trip in trips:
            await db.refresh(trip)

        log.info(
            "delivery_trips_generated",
            plan_id=plan_id,
            trip_count=len(trips),
            tenant_id=tenant_id,
        )
        return [_trip_to_dict(t) for t in trips]

    async def get_trip(
        self,
        trip_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """查询配送单详情"""
        await _set_tenant(db, tenant_id)

        trip = await db.get(DeliveryTripORM, uuid.UUID(trip_id))
        if not trip or trip.is_deleted:
            raise ValueError(f"配送单 {trip_id} 不存在")
        if str(trip.tenant_id) != tenant_id:
            raise ValueError(f"配送单 {trip_id} 不存在")
        return _trip_to_dict(trip)

    async def get_variance_report(
        self,
        plan_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """生成差异报告（实收 vs 计划）"""
        await _set_tenant(db, tenant_id)

        plan = await db.get(ProductionPlanORM, uuid.UUID(plan_id))
        if not plan or plan.is_deleted:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if str(plan.tenant_id) != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")

        # 查询该计划下所有配送行程及明细
        stmt = (
            select(DeliveryTripORM)
            .where(
                and_(
                    DeliveryTripORM.plan_id == uuid.UUID(plan_id),
                    DeliveryTripORM.tenant_id == uuid.UUID(tenant_id),
                    DeliveryTripORM.is_deleted == False,  # noqa: E712
                )
            )
        )
        result = await db.execute(stmt)
        db_trips = result.scalars().all()

        variance_lines: List[Dict[str, Any]] = []
        disputed_count = 0
        for trip in db_trips:
            for item in trip.items:
                if item.received_qty is not None:
                    variance = float(item.received_qty) - float(item.planned_qty)
                    variance_pct = (
                        variance / float(item.planned_qty) * 100 if float(item.planned_qty) else 0
                    )
                    variance_lines.append({
                        "trip_id": str(trip.id),
                        "trip_no": trip.trip_no,
                        "store_id": str(item.store_id),
                        "ingredient_id": str(item.ingredient_id),
                        "planned_qty": float(item.planned_qty),
                        "received_qty": float(item.received_qty),
                        "variance_qty": round(variance, 3),
                        "variance_pct": round(variance_pct, 2),
                        "status": item.status,
                    })
                    if item.status == "disputed":
                        disputed_count += 1

        plan_date_str = plan.plan_date.isoformat() if hasattr(plan.plan_date, "isoformat") else str(plan.plan_date)
        return {
            "plan_id": str(plan.id),
            "plan_date": plan_date_str,
            "kitchen_id": str(plan.kitchen_id),
            "total_lines": len(variance_lines),
            "disputed_count": disputed_count,
            "lines": variance_lines,
        }


# ─── 内部路线辅助（避免循环导入） ───


class _DeliveryRouteHelper:
    """轻量路线优化辅助，供 generate_delivery_trips 内部使用。
    完整实现参见 delivery_route_service.DeliveryRouteService。
    """

    def _get_store_geo(self, store_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return _store_geo.get(f"{tenant_id}:{store_id}")

    def cluster_stores_by_region(
        self,
        store_ids: List[str],
        tenant_id: str,
        max_per_trip: int = 6,
    ) -> List[List[str]]:
        stores_with_geo: List[tuple[str, float, float]] = []
        stores_without_geo: List[str] = []
        for store_id in store_ids:
            geo = self._get_store_geo(store_id, tenant_id)
            if geo and "lat" in geo and "lng" in geo:
                stores_with_geo.append((store_id, geo["lat"], geo["lng"]))
            else:
                stores_without_geo.append(store_id)

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
