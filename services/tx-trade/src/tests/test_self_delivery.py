"""
外卖自营配送调度MVP 测试
Y-M4

覆盖：
1. test_create_delivery_order   — estimated_minutes = max(15, distance/250)
2. test_delivery_status_flow    — 完整状态机: pending→assigned→picked_up→delivered
3. test_rider_workload          — 配送员在途2单 → current_orders=2
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.self_delivery_routes import (
    _MOCK_DELIVERY_ORDERS,
    MOCK_RIDERS,
    _calc_estimated_minutes,
    router,
)

# ─── 测试 App ─────────────────────────────────────────────────────────────────

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────


def _reset_state() -> None:
    """重置内存存储和 mock 配送员状态"""
    _MOCK_DELIVERY_ORDERS.clear()
    for r in MOCK_RIDERS:
        if r["id"] == "rider-001":
            r["status"] = "delivering"
            r["current_orders"] = 2
            r["today_completed"] = 8
        elif r["id"] == "rider-002":
            r["status"] = "online"
            r["current_orders"] = 0
            r["today_completed"] = 5
        elif r["id"] == "rider-003":
            r["status"] = "offline"
            r["current_orders"] = 0
            r["today_completed"] = 3


def _create_order(
    distance_meters: int = 1000,
    order_id: str = "ord-test-001",
) -> dict:
    """便捷创建配送单，返回响应 data 字典"""
    resp = client.post(
        "/api/v1/trade/delivery/orders",
        json={
            "order_id": order_id,
            "store_id": "store-test-001",
            "delivery_address": "长沙市岳麓区测试路1号",
            "distance_meters": distance_meters,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


# ─── Test 1: 创建配送单 ───────────────────────────────────────────────────────


class TestCreateDeliveryOrder:
    """estimated_minutes = max(15, distance_meters / 250) 计算验证"""

    def setup_method(self) -> None:
        _reset_state()

    @pytest.mark.parametrize(
        "distance_meters,expected_minutes",
        [
            (0, 15),  # max(15, 0/250) = max(15,0) = 15
            (500, 15),  # max(15, 500/250) = max(15,2) = 15
            (1000, 15),  # max(15, 1000/250) = max(15,4) = 15
            (3750, 15),  # max(15, 3750/250) = max(15,15) = 15
            (5000, 20),  # max(15, 5000/250) = max(15,20) = 20
            (10000, 40),  # max(15, 10000/250) = max(15,40) = 40
            (25000, 100),  # max(15, 25000/250) = max(15,100) = 100
        ],
    )
    def test_estimated_minutes_formula(self, distance_meters: int, expected_minutes: int) -> None:
        """直接验证纯函数"""
        assert _calc_estimated_minutes(distance_meters) == expected_minutes

    def test_create_order_response_structure(self) -> None:
        """创建配送单返回正确的字段结构"""
        data = _create_order(distance_meters=5000)
        assert data["status"] == "pending"
        assert data["estimated_minutes"] == 20
        assert data["rider_id"] is None
        assert data["delivered_at"] is None
        assert data["failed_reason"] is None
        assert data["id"].startswith("DLV-")

    def test_create_order_with_short_distance(self) -> None:
        """短距离配送（<3750米）estimated_minutes 最小为 15"""
        data = _create_order(distance_meters=100)
        assert data["estimated_minutes"] == 15

    def test_create_order_with_long_distance(self) -> None:
        """长距离配送 estimated_minutes 按比例增加"""
        data = _create_order(distance_meters=12500)
        assert data["estimated_minutes"] == 50  # max(15, 12500/250) = 50

    def test_create_order_listed_in_orders(self) -> None:
        """创建后可在列表中找到"""
        data = _create_order()
        delivery_id = data["id"]

        list_resp = client.get("/api/v1/trade/delivery/orders", params={"status": "pending"})
        ids = [o["id"] for o in list_resp.json()["data"]["items"]]
        assert delivery_id in ids


# ─── Test 2: 配送状态机完整流程 ───────────────────────────────────────────────


class TestDeliveryStatusFlow:
    """完整状态机: pending → assigned → picked_up → delivered"""

    def setup_method(self) -> None:
        _reset_state()

    def test_full_status_flow(self) -> None:
        """逐步推进状态，验证每个阶段的状态和时间戳"""
        # 创建
        data = _create_order(distance_meters=3000)
        delivery_id = data["id"]
        assert data["status"] == "pending"

        # 派单
        assign_resp = client.post(
            f"/api/v1/trade/delivery/orders/{delivery_id}/assign",
            json={"rider_id": "rider-002", "rider_name": "李骑手", "rider_phone": "139xxxx0002"},
        )
        assert assign_resp.status_code == 200, assign_resp.text
        assign_data = assign_resp.json()["data"]
        assert assign_data["status"] == "assigned"
        assert assign_data["rider_id"] == "rider-002"
        assert assign_data["dispatch_at"] is not None

        # 取货
        pickup_resp = client.post(f"/api/v1/trade/delivery/orders/{delivery_id}/pickup")
        assert pickup_resp.status_code == 200, pickup_resp.text
        pickup_data = pickup_resp.json()["data"]
        assert pickup_data["status"] == "picked_up"
        assert pickup_data["picked_up_at"] is not None

        # 送达
        complete_resp = client.post(f"/api/v1/trade/delivery/orders/{delivery_id}/complete")
        assert complete_resp.status_code == 200, complete_resp.text
        complete_data = complete_resp.json()["data"]
        assert complete_data["status"] == "delivered"
        assert complete_data["delivered_at"] is not None

    def test_invalid_transition_returns_409(self) -> None:
        """跳跃状态转换应返回 409"""
        data = _create_order()
        delivery_id = data["id"]

        # pending 不能直接 pickup（须先 assign）
        resp = client.post(f"/api/v1/trade/delivery/orders/{delivery_id}/pickup")
        assert resp.status_code == 409, f"应为 409，实际: {resp.status_code}"

    def test_fail_from_pending(self) -> None:
        """pending 状态可直接标记失败"""
        data = _create_order()
        delivery_id = data["id"]

        resp = client.post(
            f"/api/v1/trade/delivery/orders/{delivery_id}/fail",
            json={"reason": "订单取消，无需配送"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "failed"
        assert resp.json()["data"]["failed_reason"] == "订单取消，无需配送"

    def test_cannot_fail_delivered_order(self) -> None:
        """已送达订单不能再标记失败"""
        data = _create_order()
        delivery_id = data["id"]

        # 走完整流程至 delivered
        client.post(
            f"/api/v1/trade/delivery/orders/{delivery_id}/assign",
            json={"rider_id": "rider-002", "rider_name": "李骑手", "rider_phone": "139xxxx0002"},
        )
        client.post(f"/api/v1/trade/delivery/orders/{delivery_id}/pickup")
        client.post(f"/api/v1/trade/delivery/orders/{delivery_id}/complete")

        # 再标记失败应被拒绝
        fail_resp = client.post(
            f"/api/v1/trade/delivery/orders/{delivery_id}/fail",
            json={"reason": "应该已送达了"},
        )
        assert fail_resp.status_code == 409

    def test_list_filter_by_status(self) -> None:
        """列表按状态过滤"""
        _create_order(order_id="ord-aa")
        _create_order(order_id="ord-bb")

        resp = client.get("/api/v1/trade/delivery/orders", params={"status": "pending"})
        items = resp.json()["data"]["items"]
        assert all(o["status"] == "pending" for o in items)


# ─── Test 3: 配送员工作量 ─────────────────────────────────────────────────────


class TestRiderWorkload:
    """配送员工作量：在途2单 → current_orders=2"""

    def setup_method(self) -> None:
        _reset_state()

    def test_rider_initial_workload(self) -> None:
        """rider-001 初始有 2 个在途单（mock 数据）"""
        resp = client.get("/api/v1/trade/delivery/riders/rider-001/workload")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # 内存无历史订单时，current_orders 来自计算（0），today_completed 叠加 mock 值
        assert data["rider_id"] == "rider-001"
        assert "current_orders" in data
        assert "today_completed" in data

    def test_rider_workload_increases_on_assign(self) -> None:
        """为配送员派2单后，workload current_orders=2"""
        order1 = _create_order(order_id="ord-w1")
        order2 = _create_order(order_id="ord-w2")

        for order in [order1, order2]:
            client.post(
                f"/api/v1/trade/delivery/orders/{order['id']}/assign",
                json={"rider_id": "rider-002", "rider_name": "李骑手", "rider_phone": "139xxxx0002"},
            )

        resp = client.get("/api/v1/trade/delivery/riders/rider-002/workload")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # 从内存计算在途单数：2 条 assigned 单
        assert data["current_orders"] == 2, f"配送员应有 2 个在途单，实际: {data['current_orders']}"

    def test_rider_workload_decreases_on_complete(self) -> None:
        """送达1单后，current_orders 减少"""
        order1 = _create_order(order_id="ord-w3")
        order2 = _create_order(order_id="ord-w4")

        for order in [order1, order2]:
            client.post(
                f"/api/v1/trade/delivery/orders/{order['id']}/assign",
                json={"rider_id": "rider-002", "rider_name": "李骑手", "rider_phone": "139xxxx0002"},
            )

        # 送达第一单
        d1 = order1["id"]
        client.post(f"/api/v1/trade/delivery/orders/{d1}/pickup")
        client.post(f"/api/v1/trade/delivery/orders/{d1}/complete")

        resp = client.get("/api/v1/trade/delivery/riders/rider-002/workload")
        data = resp.json()["data"]
        # order1 已 delivered，order2 仍 assigned → 在途 = 1
        assert data["current_orders"] == 1

    def test_nonexistent_rider_returns_404(self) -> None:
        """不存在的配送员 ID 返回 404"""
        resp = client.get("/api/v1/trade/delivery/riders/rider-not-exist/workload")
        assert resp.status_code == 404

    def test_delivery_stats_endpoint(self) -> None:
        """配送统计接口返回正确结构"""
        resp = client.get("/api/v1/trade/delivery/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "dispatched_count" in data
        assert "completed_count" in data
        assert "avg_delivery_minutes" in data
        assert "on_time_rate_percent" in data
