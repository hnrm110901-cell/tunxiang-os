"""中央厨房生产计划服务

流程: 需求汇总 → 生产任务 → 产能检查 → 生产执行 → 配送任务生成

注：本文件自包含，不使用包内相对导入，与项目其他服务文件保持一致。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 中央厨房产能上限（单位：kg / 天，可由环境变量或配置表覆盖）
DEFAULT_KITCHEN_CAPACITY_KG = 5000.0

# 档口分配规则（原料类型 → 加工档口）
STATION_MAPPING: Dict[str, str] = {
    "meat": "档口A-肉类加工",
    "vegetable": "档口B-蔬菜清洗",
    "seafood": "档口C-海鲜处理",
    "grain": "档口D-主食加工",
    "sauce": "档口E-调料配制",
    "default": "档口F-综合加工",
}

# ─── 内存存储（生产环境替换为 DB Repository） ───
_plans: Dict[str, Dict[str, Any]] = {}
_tasks: Dict[str, Dict[str, Any]] = {}
_trips: Dict[str, Dict[str, Any]] = {}
_items: Dict[str, Dict[str, Any]] = {}

# ─── 测试注入存储 ───
_store_demands: Dict[str, List[Dict[str, Any]]] = {}
_store_geo: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _clear_store() -> None:
    """测试辅助：清空所有内存存储"""
    _plans.clear()
    _tasks.clear()
    _trips.clear()
    _items.clear()
    _store_demands.clear()
    _store_geo.clear()


def inject_store_demand(store_id: str, tenant_id: str, demands: List[Dict[str, Any]]) -> None:
    """注入门店需求（测试用）"""
    _store_demands[f"{tenant_id}:{store_id}"] = demands


def inject_store_geo(store_id: str, tenant_id: str, geo: Dict[str, Any]) -> None:
    """注入门店地理信息（测试用）"""
    _store_geo[f"{tenant_id}:{store_id}"] = geo


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


class ProductionPlanService:

    async def generate_plan(
        self,
        kitchen_id: str,
        plan_date: str,
        tenant_id: str,
        store_ids: List[str],
        db: Any = None,
        created_by: Optional[str] = None,
        capacity_kg: float = DEFAULT_KITCHEN_CAPACITY_KG,
    ) -> Dict[str, Any]:
        """根据各门店次日需求量生成生产计划。

        Args:
            kitchen_id: 中央厨房 ID
            plan_date: 生产日期（YYYY-MM-DD）
            tenant_id: 租户 ID（显式传入，不从 session 读取）
            store_ids: 参与汇总的门店 ID 列表
            db: 数据库会话（当前阶段使用内存存储，接口预留）
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
        plan_id = _gen_id("plan")
        now = _now_iso()
        plan: Dict[str, Any] = {
            "id": plan_id,
            "tenant_id": tenant_id,
            "kitchen_id": kitchen_id,
            "plan_date": plan_date,
            "status": "draft",
            "total_items": len(aggregated),
            "created_by": created_by,
            "created_at": now,
            "tasks": [],
        }
        _plans[plan_id] = plan

        # 4. 按加工工艺分组，生成 ProductionTask 列表
        for agg_item in aggregated:
            category = agg_item.get("category", "default")
            station = STATION_MAPPING.get(category, STATION_MAPPING["default"])
            task_id = _gen_id("task")
            task: Dict[str, Any] = {
                "id": task_id,
                "tenant_id": tenant_id,
                "plan_id": plan_id,
                "ingredient_id": agg_item["ingredient_id"],
                "planned_qty": agg_item["total_qty"],
                "unit": agg_item["unit"],
                "assigned_station": station,
                "status": "pending",
                "actual_qty": None,
                "started_at": None,
                "completed_at": None,
            }
            _tasks[task_id] = task
            plan["tasks"].append(task)

        log.info(
            "production_plan_generated",
            plan_id=plan_id,
            task_count=len(plan["tasks"]),
            tenant_id=tenant_id,
        )
        return plan

    async def list_plans(
        self,
        kitchen_id: str,
        plan_date: Optional[str],
        tenant_id: str,
        db: Any = None,
    ) -> List[Dict[str, Any]]:
        """查询生产计划列表（按 kitchen_id 和可选日期过滤）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        results = []
        for plan in _plans.values():
            if plan["tenant_id"] != tenant_id:
                continue
            if plan["kitchen_id"] != kitchen_id:
                continue
            if plan_date and plan["plan_date"] != plan_date:
                continue
            results.append(plan)
        return results

    async def confirm_plan(
        self,
        plan_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> Dict[str, Any]:
        """确认计划，锁定生产任务。

        Raises:
            ValueError: 计划不存在、租户不匹配或状态不允许确认
        """
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["tenant_id"] != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        if plan["status"] != "draft":
            raise ValueError(f"计划状态为 {plan['status']}，只有 draft 状态可以确认")

        plan["status"] = "confirmed"
        log.info("production_plan_confirmed", plan_id=plan_id, tenant_id=tenant_id)
        return plan

    async def complete_task(
        self,
        task_id: str,
        actual_qty: float,
        tenant_id: str,
        db: Any = None,
    ) -> Dict[str, Any]:
        """加工完成，记录实际产量。

        Raises:
            ValueError: 任务不存在、租户不匹配或数量非法
        """
        task = _tasks.get(task_id)
        if not task:
            raise ValueError(f"生产任务 {task_id} 不存在")
        if task["tenant_id"] != tenant_id:
            raise ValueError(f"生产任务 {task_id} 不属于当前租户")
        if actual_qty < 0:
            raise ValueError("实际产量不能为负数")
        if task["status"] == "done":
            raise ValueError(f"生产任务 {task_id} 已完成，不能重复提交")

        now = _now_iso()
        if task["status"] == "pending":
            task["started_at"] = now
        task["status"] = "done"
        task["actual_qty"] = actual_qty
        task["completed_at"] = now

        # 检查计划下所有任务是否都已完成
        plan = _plans.get(task["plan_id"])
        if plan:
            all_done = all(t["status"] == "done" for t in plan["tasks"])
            if all_done and plan["status"] == "confirmed":
                plan["status"] = "in_progress"
                log.info(
                    "all_tasks_done_plan_in_progress",
                    plan_id=plan["id"],
                    tenant_id=tenant_id,
                )

        log.info(
            "production_task_completed",
            task_id=task_id,
            actual_qty=actual_qty,
            tenant_id=tenant_id,
        )
        return task

    async def generate_delivery_trips(
        self,
        plan_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> List[Dict[str, Any]]:
        """生产完成后生成配送任务（按门店地理位置聚类优化路线）。

        Raises:
            ValueError: 计划不存在、租户不匹配或需求数据缺失
        """
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["tenant_id"] != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        if plan["status"] not in ("in_progress", "confirmed"):
            raise ValueError(
                f"计划状态为 {plan['status']}，需要 confirmed 或 in_progress 才能生成配送任务"
            )

        # 收集各门店对应的配送明细
        store_item_map: Dict[str, List[Dict[str, Any]]] = {}
        for task in plan["tasks"]:
            for key, demands in _store_demands.items():
                key_tenant, store_id = key.split(":", 1)
                if key_tenant != tenant_id:
                    continue
                for d in demands:
                    if d["ingredient_id"] == task["ingredient_id"]:
                        if store_id not in store_item_map:
                            store_item_map[store_id] = []
                        store_item_map[store_id].append({
                            "ingredient_id": task["ingredient_id"],
                            "planned_qty": float(d.get("quantity", 0)),
                            "unit": task["unit"],
                        })

        if not store_item_map:
            raise ValueError("未找到任何门店配送需求，请先注入门店需求数据")

        # 按地理位置聚类分组
        route_svc = _DeliveryRouteHelper()
        store_groups = route_svc.cluster_stores_by_region(
            list(store_item_map.keys()), tenant_id
        )

        trips: List[Dict[str, Any]] = []
        trip_counter = 1
        for group in store_groups:
            trip_id = _gen_id("trip")
            trip_no = f"TRP-{plan_date_short(plan['plan_date'])}-{trip_counter:02d}"

            # 路线排序
            route_seq = route_svc.build_route_sequence(group, tenant_id)

            trip: Dict[str, Any] = {
                "id": trip_id,
                "tenant_id": tenant_id,
                "plan_id": plan_id,
                "trip_no": trip_no,
                "driver_name": None,
                "vehicle_plate": None,
                "departure_time": None,
                "status": "pending",
                "route_sequence": route_seq,
                "created_at": _now_iso(),
                "items": [],
            }

            # 生成配送明细
            for seq_entry in route_seq:
                store_id = seq_entry["store_id"]
                for ing_item in store_item_map.get(store_id, []):
                    item_id = _gen_id("ditem")
                    d_item: Dict[str, Any] = {
                        "id": item_id,
                        "tenant_id": tenant_id,
                        "trip_id": trip_id,
                        "store_id": store_id,
                        "ingredient_id": ing_item["ingredient_id"],
                        "planned_qty": ing_item["planned_qty"],
                        "received_qty": None,
                        "variance_qty": None,
                        "received_at": None,
                        "status": "pending",
                    }
                    _items[item_id] = d_item
                    trip["items"].append(d_item)

            _trips[trip_id] = trip
            trips.append(trip)
            trip_counter += 1

        # 更新计划状态
        plan["status"] = "in_progress"
        log.info(
            "delivery_trips_generated",
            plan_id=plan_id,
            trip_count=len(trips),
            tenant_id=tenant_id,
        )
        return trips

    async def get_variance_report(
        self,
        plan_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> Dict[str, Any]:
        """生成差异报告（实收 vs 计划）"""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["tenant_id"] != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")

        variance_lines = []
        disputed_count = 0
        for trip_id, trip in _trips.items():
            if trip["plan_id"] != plan_id or trip["tenant_id"] != tenant_id:
                continue
            for item in trip["items"]:
                if item["received_qty"] is not None:
                    variance = item["received_qty"] - item["planned_qty"]
                    variance_pct = (
                        variance / item["planned_qty"] * 100 if item["planned_qty"] else 0
                    )
                    variance_lines.append({
                        "trip_id": trip_id,
                        "trip_no": trip["trip_no"],
                        "store_id": item["store_id"],
                        "ingredient_id": item["ingredient_id"],
                        "planned_qty": item["planned_qty"],
                        "received_qty": item["received_qty"],
                        "variance_qty": round(variance, 3),
                        "variance_pct": round(variance_pct, 2),
                        "status": item["status"],
                    })
                    if item["status"] == "disputed":
                        disputed_count += 1

        return {
            "plan_id": plan_id,
            "plan_date": plan["plan_date"],
            "kitchen_id": plan["kitchen_id"],
            "total_lines": len(variance_lines),
            "disputed_count": disputed_count,
            "lines": variance_lines,
        }


# ─── 内部路线辅助（避免循环导入） ───

import math


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
        stores_with_geo = []
        stores_without_geo = []
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
