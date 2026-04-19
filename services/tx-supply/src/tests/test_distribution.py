"""中央仓配送调度测试 -- 计划 / 路线优化 / 派车 / 签收 / 看板"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.distribution import (
    DeliveryItemStatus,
    DistributionStatus,
    _clear_store,
    confirm_delivery,
    create_distribution_plan,
    dispatch_delivery,
    get_distribution_dashboard,
    inject_driver,
    inject_store_geo,
    inject_warehouse,
    optimize_route,
)

TENANT = "tenant-dist-001"
WAREHOUSE_ID = "wh-central-001"


def _setup_warehouse_and_stores():
    """注入仓库 + 3个门店地理信息"""
    inject_warehouse(
        WAREHOUSE_ID,
        TENANT,
        {
            "warehouse_name": "长沙中央仓",
            "lat": 28.2280,
            "lng": 112.9388,
            "address": "长沙市岳麓区中央仓库",
            "capacity": 10000,
        },
    )
    inject_store_geo(
        "store-a",
        TENANT,
        {
            "store_name": "五一广场店",
            "lat": 28.1978,
            "lng": 112.9762,
            "address": "长沙市五一广场",
        },
    )
    inject_store_geo(
        "store-b",
        TENANT,
        {
            "store_name": "橘子洲店",
            "lat": 28.2104,
            "lng": 112.9539,
            "address": "长沙市橘子洲",
        },
    )
    inject_store_geo(
        "store-c",
        TENANT,
        {
            "store_name": "星沙店",
            "lat": 28.2455,
            "lng": 113.0802,
            "address": "长沙县星沙",
        },
    )
    inject_driver(
        "driver-001",
        TENANT,
        {
            "driver_name": "刘师傅",
            "phone": "139****5678",
            "vehicle_no": "湘A12345",
            "vehicle_type": "冷藏车",
            "capacity_kg": 2000,
        },
    )


def _create_test_plan():
    """创建测试配送计划"""
    return create_distribution_plan(
        warehouse_id=WAREHOUSE_ID,
        store_orders=[
            {
                "store_id": "store-a",
                "items": [
                    {"item_id": "item-1", "item_name": "五花肉", "quantity": 20, "unit": "kg"},
                    {"item_id": "item-2", "item_name": "生菜", "quantity": 10, "unit": "kg"},
                ],
            },
            {
                "store_id": "store-b",
                "items": [
                    {"item_id": "item-3", "item_name": "鸡蛋", "quantity": 100, "unit": "个"},
                ],
            },
            {
                "store_id": "store-c",
                "items": [
                    {"item_id": "item-4", "item_name": "大米", "quantity": 50, "unit": "kg"},
                ],
            },
        ],
        tenant_id=TENANT,
    )


class TestCreateDistributionPlan:
    def setup_method(self):
        _clear_store()
        _setup_warehouse_and_stores()

    def test_create_plan_basic(self):
        plan = _create_test_plan()
        assert plan["status"] == DistributionStatus.planned.value
        assert plan["store_count"] == 3
        assert plan["total_items"] == 4
        assert plan["warehouse_id"] == WAREHOUSE_ID

    def test_create_plan_has_deliveries(self):
        plan = _create_test_plan()
        assert len(plan["store_deliveries"]) == 3
        for sd in plan["store_deliveries"]:
            assert sd["status"] == DeliveryItemStatus.pending.value
            assert "delivery_id" in sd

    def test_create_plan_empty_orders_raises(self):
        try:
            create_distribution_plan(WAREHOUSE_ID, [], TENANT)
            assert False, "应该抛出 ValueError"
        except ValueError as e:
            assert "store_orders" in str(e)

    def test_create_plan_tenant_required(self):
        try:
            create_distribution_plan(WAREHOUSE_ID, [{"store_id": "s1", "items": []}], "")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

    def test_plan_items_status_pending(self):
        plan = _create_test_plan()
        for sd in plan["store_deliveries"]:
            for item in sd["items"]:
                assert item["status"] == DeliveryItemStatus.pending.value


class TestOptimizeRoute:
    def setup_method(self):
        _clear_store()
        _setup_warehouse_and_stores()

    def test_optimize_returns_route(self):
        plan = _create_test_plan()
        result = optimize_route(plan["plan_id"], TENANT)
        assert result["optimized"] is True
        assert len(result["route"]) == 3
        assert result["total_distance_km"] > 0

    def test_route_sequences(self):
        plan = _create_test_plan()
        result = optimize_route(plan["plan_id"], TENANT)
        sequences = [r["sequence"] for r in result["route"]]
        assert sequences == [1, 2, 3]

    def test_route_cumulative_distance(self):
        plan = _create_test_plan()
        result = optimize_route(plan["plan_id"], TENANT)
        cums = [r["cumulative_km"] for r in result["route"]]
        assert cums == sorted(cums)

    def test_route_estimated_duration(self):
        plan = _create_test_plan()
        result = optimize_route(plan["plan_id"], TENANT)
        assert result["estimated_duration_min"] > 0

    def test_optimize_invalid_plan(self):
        try:
            optimize_route("nonexistent-plan", TENANT)
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


class TestDispatchDelivery:
    def setup_method(self):
        _clear_store()
        _setup_warehouse_and_stores()

    def test_dispatch_changes_status(self):
        plan = _create_test_plan()
        result = dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        assert result["status"] == DistributionStatus.dispatched.value
        assert result["driver_id"] == "driver-001"
        assert result["dispatched_at"] is not None

    def test_dispatch_loads_items(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        # 验证内部状态（通过 dashboard 间接检查）
        dashboard = get_distribution_dashboard(WAREHOUSE_ID, TENANT)
        assert dashboard["summary"]["dispatched"] >= 1

    def test_dispatch_already_dispatched_raises(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        try:
            dispatch_delivery(plan["plan_id"], "driver-002", TENANT)
            assert False, "应该抛出 ValueError"
        except ValueError as e:
            assert "planned" in str(e)

    def test_dispatch_includes_driver_info(self):
        plan = _create_test_plan()
        result = dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        assert result["driver_info"] is not None
        assert result["driver_info"]["driver_name"] == "刘师傅"

    def test_dispatch_tenant_isolation(self):
        plan = _create_test_plan()
        try:
            dispatch_delivery(plan["plan_id"], "driver-001", "other-tenant")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


class TestConfirmDelivery:
    def setup_method(self):
        _clear_store()
        _setup_warehouse_and_stores()

    def test_confirm_single_store(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        result = confirm_delivery(
            plan["plan_id"],
            "store-a",
            [
                {"item_id": "item-1", "received_quantity": 20, "status": "accepted"},
                {"item_id": "item-2", "received_quantity": 10, "status": "accepted"},
            ],
            TENANT,
        )
        assert len(result["confirmed_items"]) == 2
        assert len(result["rejected_items"]) == 0

    def test_confirm_all_stores_completes_plan(self):
        plan = _create_test_plan()
        pid = plan["plan_id"]
        dispatch_delivery(pid, "driver-001", TENANT)

        confirm_delivery(
            pid,
            "store-a",
            [
                {"item_id": "item-1", "received_quantity": 20, "status": "accepted"},
                {"item_id": "item-2", "received_quantity": 10, "status": "accepted"},
            ],
            TENANT,
        )
        confirm_delivery(
            pid,
            "store-b",
            [
                {"item_id": "item-3", "received_quantity": 100, "status": "accepted"},
            ],
            TENANT,
        )
        result = confirm_delivery(
            pid,
            "store-c",
            [
                {"item_id": "item-4", "received_quantity": 50, "status": "accepted"},
            ],
            TENANT,
        )

        assert result["plan_status"] == DistributionStatus.delivered.value

    def test_confirm_with_rejection(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        result = confirm_delivery(
            plan["plan_id"],
            "store-a",
            [
                {"item_id": "item-1", "received_quantity": 20, "status": "accepted"},
                {"item_id": "item-2", "received_quantity": 0, "status": "rejected", "notes": "变质"},
            ],
            TENANT,
        )
        assert len(result["rejected_items"]) == 1
        assert result["rejected_items"][0]["reason"] == "变质"

    def test_confirm_planned_raises(self):
        plan = _create_test_plan()
        try:
            confirm_delivery(plan["plan_id"], "store-a", [], TENANT)
            assert False, "应该抛出 ValueError"
        except ValueError as e:
            assert "dispatched" in str(e)

    def test_confirm_invalid_store_raises(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        try:
            confirm_delivery(plan["plan_id"], "store-nonexistent", [], TENANT)
            assert False, "应该抛出 ValueError"
        except ValueError as e:
            assert "未找到门店" in str(e)


class TestGetDistributionDashboard:
    def setup_method(self):
        _clear_store()
        _setup_warehouse_and_stores()

    def test_dashboard_empty(self):
        result = get_distribution_dashboard(WAREHOUSE_ID, TENANT)
        assert result["summary"]["total_plans"] == 0
        assert result["completion_rate"] == 0.0

    def test_dashboard_with_plans(self):
        _create_test_plan()
        _create_test_plan()
        result = get_distribution_dashboard(WAREHOUSE_ID, TENANT)
        assert result["summary"]["total_plans"] == 2
        assert result["summary"]["planned"] == 2

    def test_dashboard_active_deliveries(self):
        plan = _create_test_plan()
        dispatch_delivery(plan["plan_id"], "driver-001", TENANT)
        result = get_distribution_dashboard(WAREHOUSE_ID, TENANT)
        assert len(result["active_deliveries"]) == 1

    def test_dashboard_completion_rate(self):
        p1 = _create_test_plan()
        _create_test_plan()
        dispatch_delivery(p1["plan_id"], "driver-001", TENANT)
        for sd in ["store-a", "store-b", "store-c"]:
            confirm_delivery(p1["plan_id"], sd, [], TENANT)
        result = get_distribution_dashboard(WAREHOUSE_ID, TENANT)
        assert result["completion_rate"] == 0.5

    def test_dashboard_tenant_isolation(self):
        _create_test_plan()
        result = get_distribution_dashboard(WAREHOUSE_ID, "other-tenant")
        assert result["summary"]["total_plans"] == 0
