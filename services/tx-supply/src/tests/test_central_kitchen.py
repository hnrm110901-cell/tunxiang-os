"""中央厨房完整链路测试

覆盖场景:
1. 根据各门店次日需求量生成生产计划
2. 生产任务分配给加工档口
3. 生产完成后生成配送任务
4. 配送路线优化（多店按地理聚类）
5. 门店确认签收后更新库存
6. 签收差异记录（实收 vs 计划）
7. tenant_id 隔离
"""

import os
import sys

# 将 src/ 目录加入 Python 路径，与其他测试文件保持一致
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.delivery_route_service import DeliveryRouteService
from services.production_plan_service import (
    ProductionPlanService,
    _clear_store,
    inject_store_demand,
    inject_store_geo,
)

TENANT = "tenant-ck-001"
OTHER_TENANT = "tenant-ck-999"
KITCHEN_ID = "kitchen-central-001"
PLAN_DATE = "2026-03-31"

STORE_A = "store-ck-a"
STORE_B = "store-ck-b"
STORE_C = "store-ck-c"


def _setup_store_demands():
    """注入三个门店的原料需求"""
    inject_store_demand(
        STORE_A,
        TENANT,
        [
            {
                "ingredient_id": "ing-pork",
                "ingredient_name": "五花肉",
                "quantity": 20.0,
                "unit": "kg",
                "category": "meat",
            },
            {
                "ingredient_id": "ing-lettuce",
                "ingredient_name": "生菜",
                "quantity": 10.0,
                "unit": "kg",
                "category": "vegetable",
            },
        ],
    )
    inject_store_demand(
        STORE_B,
        TENANT,
        [
            {
                "ingredient_id": "ing-pork",
                "ingredient_name": "五花肉",
                "quantity": 15.0,
                "unit": "kg",
                "category": "meat",
            },
            {
                "ingredient_id": "ing-rice",
                "ingredient_name": "大米",
                "quantity": 30.0,
                "unit": "kg",
                "category": "grain",
            },
        ],
    )
    inject_store_demand(
        STORE_C,
        TENANT,
        [
            {
                "ingredient_id": "ing-lettuce",
                "ingredient_name": "生菜",
                "quantity": 8.0,
                "unit": "kg",
                "category": "vegetable",
            },
            {
                "ingredient_id": "ing-rice",
                "ingredient_name": "大米",
                "quantity": 20.0,
                "unit": "kg",
                "category": "grain",
            },
        ],
    )


def _setup_store_geo():
    """注入门店地理信息"""
    inject_store_geo(
        STORE_A,
        TENANT,
        {
            "store_name": "五一广场店",
            "lat": 28.1978,
            "lng": 112.9762,
            "address": "长沙市五一广场",
            "sort_order": 1,
        },
    )
    inject_store_geo(
        STORE_B,
        TENANT,
        {
            "store_name": "橘子洲店",
            "lat": 28.2104,
            "lng": 112.9539,
            "address": "长沙市橘子洲",
            "sort_order": 2,
        },
    )
    inject_store_geo(
        STORE_C,
        TENANT,
        {
            "store_name": "星沙店",
            "lat": 28.2455,
            "lng": 113.0802,
            "address": "长沙县星沙",
            "sort_order": 3,
        },
    )


def setup_function():
    _clear_store()
    _setup_store_demands()
    _setup_store_geo()


# ────────────────────────────────────────────────────────────
# 1. 生成生产计划
# ────────────────────────────────────────────────────────────


class TestGeneratePlan:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def test_generate_plan_basic(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        assert plan["status"] == "draft"
        assert plan["kitchen_id"] == KITCHEN_ID
        assert plan["plan_date"] == PLAN_DATE
        assert plan["tenant_id"] == TENANT
        # 3种原料：ing-pork, ing-lettuce, ing-rice
        assert plan["total_items"] == 3

    @pytest.mark.asyncio
    async def test_generate_plan_creates_tasks(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        assert len(plan["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_generate_plan_aggregates_qty(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        tasks = {t["ingredient_id"]: t for t in plan["tasks"]}
        # 门店A(20) + 门店B(15) = 35kg 五花肉
        assert tasks["ing-pork"]["planned_qty"] == 35.0
        # 门店A(10) + 门店C(8) = 18kg 生菜
        assert tasks["ing-lettuce"]["planned_qty"] == 18.0
        # 门店B(30) + 门店C(20) = 50kg 大米
        assert tasks["ing-rice"]["planned_qty"] == 50.0

    @pytest.mark.asyncio
    async def test_generate_plan_empty_store_ids_raises(self):
        svc = ProductionPlanService()
        with pytest.raises(ValueError, match="store_ids"):
            await svc.generate_plan(
                kitchen_id=KITCHEN_ID,
                plan_date=PLAN_DATE,
                tenant_id=TENANT,
                store_ids=[],
            )

    @pytest.mark.asyncio
    async def test_generate_plan_empty_tenant_raises(self):
        svc = ProductionPlanService()
        with pytest.raises(ValueError, match="tenant_id"):
            await svc.generate_plan(
                kitchen_id=KITCHEN_ID,
                plan_date=PLAN_DATE,
                tenant_id="",
                store_ids=[STORE_A],
            )

    @pytest.mark.asyncio
    async def test_generate_plan_capacity_exceeded_raises(self):
        svc = ProductionPlanService()
        with pytest.raises(ValueError, match="产能上限"):
            # 设置产能上限为 1kg，肯定超出
            await svc.generate_plan(
                kitchen_id=KITCHEN_ID,
                plan_date=PLAN_DATE,
                tenant_id=TENANT,
                store_ids=[STORE_A, STORE_B, STORE_C],
                capacity_kg=1.0,
            )


# ────────────────────────────────────────────────────────────
# 2. 生产任务分配给加工档口
# ────────────────────────────────────────────────────────────


class TestTaskStationAssignment:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def test_tasks_have_assigned_station(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        for task in plan["tasks"]:
            assert task["assigned_station"] is not None
            assert len(task["assigned_station"]) > 0

    @pytest.mark.asyncio
    async def test_meat_assigned_to_meat_station(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B],
        )
        tasks = {t["ingredient_id"]: t for t in plan["tasks"]}
        assert "肉类" in tasks["ing-pork"]["assigned_station"]

    @pytest.mark.asyncio
    async def test_grain_assigned_to_grain_station(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_B, STORE_C],
        )
        tasks = {t["ingredient_id"]: t for t in plan["tasks"]}
        assert "主食" in tasks["ing-rice"]["assigned_station"]

    @pytest.mark.asyncio
    async def test_tasks_initial_status_pending(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        for task in plan["tasks"]:
            assert task["status"] == "pending"


# ────────────────────────────────────────────────────────────
# 3. 确认计划 + 加工完成
# ────────────────────────────────────────────────────────────


class TestConfirmAndCompleteTasks:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def test_confirm_plan(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B],
        )
        confirmed = await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        assert confirmed["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_plan_wrong_tenant_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        with pytest.raises(ValueError):
            await svc.confirm_plan(plan_id=plan["id"], tenant_id=OTHER_TENANT)

    @pytest.mark.asyncio
    async def test_confirm_plan_twice_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        with pytest.raises(ValueError, match="draft"):
            await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)

    @pytest.mark.asyncio
    async def test_complete_task(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        task_id = plan["tasks"][0]["id"]
        result = await svc.complete_task(task_id=task_id, actual_qty=19.5, tenant_id=TENANT)
        assert result["status"] == "done"
        assert result["actual_qty"] == 19.5
        assert result["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_complete_task_negative_qty_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        task_id = plan["tasks"][0]["id"]
        with pytest.raises(ValueError, match="负数"):
            await svc.complete_task(task_id=task_id, actual_qty=-1.0, tenant_id=TENANT)

    @pytest.mark.asyncio
    async def test_complete_task_twice_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        task_id = plan["tasks"][0]["id"]
        await svc.complete_task(task_id=task_id, actual_qty=10.0, tenant_id=TENANT)
        with pytest.raises(ValueError, match="已完成"):
            await svc.complete_task(task_id=task_id, actual_qty=10.0, tenant_id=TENANT)


# ────────────────────────────────────────────────────────────
# 4. 生成配送任务（地理聚类）
# ────────────────────────────────────────────────────────────


class TestGenerateDeliveryTrips:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def _make_confirmed_plan(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        return plan

    @pytest.mark.asyncio
    async def test_generate_trips_returns_list(self):
        plan = await self._make_confirmed_plan()
        svc = ProductionPlanService()
        trips = await svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        assert isinstance(trips, list)
        assert len(trips) >= 1

    @pytest.mark.asyncio
    async def test_trips_have_route_sequence(self):
        plan = await self._make_confirmed_plan()
        svc = ProductionPlanService()
        trips = await svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        for trip in trips:
            assert len(trip["route_sequence"]) > 0
            for seq in trip["route_sequence"]:
                assert "store_id" in seq
                assert "sequence" in seq

    @pytest.mark.asyncio
    async def test_trips_have_delivery_items(self):
        plan = await self._make_confirmed_plan()
        svc = ProductionPlanService()
        trips = await svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        total_items = sum(len(t["items"]) for t in trips)
        assert total_items > 0

    @pytest.mark.asyncio
    async def test_trips_wrong_tenant_raises(self):
        plan = await self._make_confirmed_plan()
        svc = ProductionPlanService()
        with pytest.raises(ValueError):
            await svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=OTHER_TENANT)

    @pytest.mark.asyncio
    async def test_trips_nonexistent_plan_raises(self):
        svc = ProductionPlanService()
        with pytest.raises(ValueError):
            await svc.generate_delivery_trips(plan_id="nonexistent-plan", tenant_id=TENANT)


# ────────────────────────────────────────────────────────────
# 5. 路线优化（地理聚类）
# ────────────────────────────────────────────────────────────


class TestRouteOptimization:
    def setup_method(self):
        _clear_store()
        _setup_store_geo()

    def test_cluster_stores_by_region(self):
        route_svc = DeliveryRouteService()
        groups = route_svc.cluster_stores_by_region([STORE_A, STORE_B, STORE_C], TENANT)
        total = sum(len(g) for g in groups)
        assert total == 3

    def test_build_route_sequence_with_geo(self):
        route_svc = DeliveryRouteService()
        seq = route_svc.build_route_sequence([STORE_A, STORE_B, STORE_C], TENANT)
        assert len(seq) == 3
        sequences = [s["sequence"] for s in seq]
        assert sorted(sequences) == [1, 2, 3]

    def test_build_route_sequence_without_geo_fallback(self):
        """无地理信息时按原始顺序"""
        _clear_store()  # 清空地理信息
        route_svc = DeliveryRouteService()
        seq = route_svc.build_route_sequence([STORE_A, STORE_B], TENANT)
        assert len(seq) == 2
        assert seq[0]["store_id"] == STORE_A

    def test_cluster_respects_max_per_trip(self):
        route_svc = DeliveryRouteService()
        many_stores = [f"store-{i}" for i in range(10)]
        groups = route_svc.cluster_stores_by_region(many_stores, TENANT, max_per_trip=3)
        for group in groups:
            assert len(group) <= 3


# ────────────────────────────────────────────────────────────
# 6. 门店签收 + 差异记录
# ────────────────────────────────────────────────────────────


class TestSignReceipt:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def _make_trip_with_items(self):
        """生成一个含配送明细的配送单"""
        plan_svc = ProductionPlanService()
        plan = await plan_svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await plan_svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await plan_svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await plan_svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        return plan, trips

    @pytest.mark.asyncio
    async def test_sign_receipt_exact_qty(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        # 找一个配送明细
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        result = await route_svc.sign_receipt(
            delivery_item_id=item_id,
            actual_qty=planned_qty,
            operator_id="op-001",
            tenant_id=TENANT,
        )
        assert result["status"] == "signed"
        assert result["variance_qty"] == 0.0

    @pytest.mark.asyncio
    async def test_sign_receipt_large_variance_disputed(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        # 差异超过 5%：实收减少 50%
        actual_qty = planned_qty * 0.4
        result = await route_svc.sign_receipt(
            delivery_item_id=item_id,
            actual_qty=actual_qty,
            operator_id="op-001",
            tenant_id=TENANT,
        )
        assert result["status"] == "disputed"
        assert abs(result["variance_qty"]) > 0

    @pytest.mark.asyncio
    async def test_sign_receipt_records_received_at(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        result = await route_svc.sign_receipt(
            delivery_item_id=item_id,
            actual_qty=planned_qty,
            operator_id="op-001",
            tenant_id=TENANT,
        )
        assert result["received_at"] is not None

    @pytest.mark.asyncio
    async def test_sign_receipt_wrong_tenant_raises(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        with pytest.raises(ValueError):
            await route_svc.sign_receipt(
                delivery_item_id=item_id,
                actual_qty=planned_qty,
                operator_id="op-001",
                tenant_id=OTHER_TENANT,
            )

    @pytest.mark.asyncio
    async def test_sign_receipt_twice_raises(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        await route_svc.sign_receipt(
            delivery_item_id=item_id,
            actual_qty=planned_qty,
            operator_id="op-001",
            tenant_id=TENANT,
        )
        with pytest.raises(ValueError, match="已签收"):
            await route_svc.sign_receipt(
                delivery_item_id=item_id,
                actual_qty=planned_qty,
                operator_id="op-001",
                tenant_id=TENANT,
            )

    @pytest.mark.asyncio
    async def test_sign_receipt_negative_qty_raises(self):
        plan, trips = await self._make_trip_with_items()
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        with pytest.raises(ValueError, match="负数"):
            await route_svc.sign_receipt(
                delivery_item_id=item_id,
                actual_qty=-1.0,
                operator_id="op-001",
                tenant_id=TENANT,
            )


# ────────────────────────────────────────────────────────────
# 5（续）. 签收后更新库存
# ────────────────────────────────────────────────────────────


class TestUpdateStoreInventory:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def _make_signed_trip(self):
        plan_svc = ProductionPlanService()
        plan = await plan_svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await plan_svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await plan_svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await plan_svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        route_svc = DeliveryRouteService()
        # 签收第一个配送单的所有明细
        trip = trips[0]
        for item in trip["items"]:
            await route_svc.sign_receipt(
                delivery_item_id=item["id"],
                actual_qty=item["planned_qty"],
                operator_id="op-001",
                tenant_id=TENANT,
            )
        return plan, trips[0]

    @pytest.mark.asyncio
    async def test_update_inventory_returns_records(self):
        plan, trip = await self._make_signed_trip()
        route_svc = DeliveryRouteService()
        result = await route_svc.update_store_inventory(trip_id=trip["id"], tenant_id=TENANT)
        assert result["inventory_records_created"] > 0
        assert result["trip_status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_inventory_records_have_correct_fields(self):
        plan, trip = await self._make_signed_trip()
        route_svc = DeliveryRouteService()
        result = await route_svc.update_store_inventory(trip_id=trip["id"], tenant_id=TENANT)
        for rec in result["records"]:
            assert rec["direction"] == "in"
            assert rec["source"] == "central_kitchen_delivery"
            assert rec["store_id"] in [STORE_A, STORE_B, STORE_C]
            assert rec["quantity_change"] >= 0

    @pytest.mark.asyncio
    async def test_update_inventory_unsigned_items_raises(self):
        """有未签收明细时更新库存应报错"""
        plan_svc = ProductionPlanService()
        plan = await plan_svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        await plan_svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await plan_svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await plan_svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        route_svc = DeliveryRouteService()
        # 不签收直接更新库存
        with pytest.raises(ValueError, match="未签收"):
            await route_svc.update_store_inventory(trip_id=trips[0]["id"], tenant_id=TENANT)


# ────────────────────────────────────────────────────────────
# 6. 差异报告
# ────────────────────────────────────────────────────────────


class TestVarianceReport:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def test_variance_report_basic(self):
        plan_svc = ProductionPlanService()
        plan = await plan_svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await plan_svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await plan_svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await plan_svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        route_svc = DeliveryRouteService()
        for trip in trips:
            for item in trip["items"]:
                await route_svc.sign_receipt(
                    delivery_item_id=item["id"],
                    actual_qty=item["planned_qty"],
                    operator_id="op-001",
                    tenant_id=TENANT,
                )
        report = await plan_svc.get_variance_report(plan_id=plan["id"], tenant_id=TENANT)
        assert report["plan_id"] == plan["id"]
        assert report["total_lines"] >= 0
        assert "disputed_count" in report

    @pytest.mark.asyncio
    async def test_variance_report_disputed_count(self):
        plan_svc = ProductionPlanService()
        plan = await plan_svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await plan_svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await plan_svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await plan_svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        route_svc = DeliveryRouteService()
        disputed_count = 0
        for trip in trips:
            for i, item in enumerate(trip["items"]):
                # 每隔一个制造差异
                actual = item["planned_qty"] if i % 2 == 0 else item["planned_qty"] * 0.4
                result = await route_svc.sign_receipt(
                    delivery_item_id=item["id"],
                    actual_qty=actual,
                    operator_id="op-001",
                    tenant_id=TENANT,
                )
                if result["status"] == "disputed":
                    disputed_count += 1

        report = await plan_svc.get_variance_report(plan_id=plan["id"], tenant_id=TENANT)
        assert report["disputed_count"] == disputed_count

    @pytest.mark.asyncio
    async def test_variance_report_wrong_plan_raises(self):
        plan_svc = ProductionPlanService()
        with pytest.raises(ValueError):
            await plan_svc.get_variance_report(plan_id="nonexistent", tenant_id=TENANT)


# ────────────────────────────────────────────────────────────
# 7. tenant_id 隔离
# ────────────────────────────────────────────────────────────


class TestTenantIsolation:
    def setup_method(self):
        _clear_store()
        _setup_store_demands()
        _setup_store_geo()

    @pytest.mark.asyncio
    async def test_plan_not_visible_to_other_tenant(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        plans = await svc.list_plans(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=OTHER_TENANT,
        )
        plan_ids = [p["id"] for p in plans]
        assert plan["id"] not in plan_ids

    @pytest.mark.asyncio
    async def test_confirm_plan_wrong_tenant_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        with pytest.raises(ValueError):
            await svc.confirm_plan(plan_id=plan["id"], tenant_id=OTHER_TENANT)

    @pytest.mark.asyncio
    async def test_complete_task_wrong_tenant_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A],
        )
        task_id = plan["tasks"][0]["id"]
        with pytest.raises(ValueError):
            await svc.complete_task(task_id=task_id, actual_qty=10.0, tenant_id=OTHER_TENANT)

    @pytest.mark.asyncio
    async def test_sign_receipt_wrong_tenant_raises(self):
        svc = ProductionPlanService()
        plan = await svc.generate_plan(
            kitchen_id=KITCHEN_ID,
            plan_date=PLAN_DATE,
            tenant_id=TENANT,
            store_ids=[STORE_A, STORE_B, STORE_C],
        )
        await svc.confirm_plan(plan_id=plan["id"], tenant_id=TENANT)
        for task in plan["tasks"]:
            await svc.complete_task(task_id=task["id"], actual_qty=task["planned_qty"], tenant_id=TENANT)
        trips = await svc.generate_delivery_trips(plan_id=plan["id"], tenant_id=TENANT)
        route_svc = DeliveryRouteService()
        item_id = trips[0]["items"][0]["id"]
        planned_qty = trips[0]["items"][0]["planned_qty"]
        with pytest.raises(ValueError):
            await route_svc.sign_receipt(
                delivery_item_id=item_id,
                actual_qty=planned_qty,
                operator_id="op-001",
                tenant_id=OTHER_TENANT,
            )
