"""
Y-A8 宴席支付闭环测试 — 定金/尾款状态机

覆盖：
1. test_create_banquet_order — 创建预订，验证 deposit_fen 计算 & 初始状态
2. test_pay_deposit_flow — 支付定金：状态机流转
3. test_pay_balance_requires_deposit — 尾款前置检查：定金未付时拒绝尾款
4. test_full_payment_flow — 完整流程：创建→定金→尾款→fully_paid
5. test_refund_deposit_only — 退定金：deposit_paid 可退；fully_paid 时禁止仅退定金
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ─── 测试固件 ────────────────────────────────────────────────────────────────

TENANT_ID = "t-test-banquet-001"
STORE_ID = "s-test-store-001"


# 每个测试独立的 app 实例，避免 mock 数据污染
@pytest.fixture()
def client():
    """为每个测试创建独立的 FastAPI 应用实例，MOCK 数据清空。"""
    from fastapi import FastAPI

    from ..api.banquet_order_routes import MOCK_BANQUET_ORDERS, MOCK_PAYMENTS, router

    # 每次测试前清空 mock 存储
    MOCK_BANQUET_ORDERS.clear()
    MOCK_PAYMENTS.clear()

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def headers():
    return {"X-Tenant-ID": TENANT_ID}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def create_test_order(
    client: TestClient,
    headers: dict,
    total_fen: int = 500000,
    deposit_rate: float = 0.30,
    contact_name: str = "测试预订人",
) -> dict:
    """创建一个宴席预订并返回 order 数据。"""
    resp = client.post(
        "/api/v1/trade/banquet/orders",
        json={
            "store_id": STORE_ID,
            "contact_name": contact_name,
            "contact_phone": "13800000001",
            "banquet_date": "2026-06-01",
            "banquet_time": "18:00",
            "guest_count": 30,
            "total_fen": total_fen,
            "deposit_rate": deposit_rate,
            "notes": "测试数据",
        },
        headers=headers,
    )
    assert resp.status_code == 200, f"创建订单失败：{resp.text}"
    body = resp.json()
    assert body["ok"] is True
    return body["data"]


# ─── 1. 创建宴席预订 ──────────────────────────────────────────────────────────


class TestCreateBanquetOrder:
    def test_deposit_calculation_30pct(self, client: TestClient, headers: dict):
        """deposit_fen = total_fen × 0.30，误差 ≤ 1分。"""
        total = 580000
        order = create_test_order(client, headers, total_fen=total, deposit_rate=0.30)

        expected_deposit = round(total * 0.30)
        assert abs(order["deposit_fen"] - expected_deposit) <= 1, (
            f"定金计算错误：expected={expected_deposit}, got={order['deposit_fen']}"
        )

    def test_balance_equals_total_minus_deposit(self, client: TestClient, headers: dict):
        """balance_fen = total_fen - deposit_fen。"""
        total = 580000
        order = create_test_order(client, headers, total_fen=total, deposit_rate=0.30)
        assert order["balance_fen"] == order["total_fen"] - order["deposit_fen"]

    def test_initial_status_unpaid(self, client: TestClient, headers: dict):
        """新建订单所有状态均为 unpaid / pending。"""
        order = create_test_order(client, headers)
        assert order["deposit_status"] == "unpaid"
        assert order["balance_status"] == "unpaid"
        assert order["payment_status"] == "unpaid"
        assert order["status"] == "pending"

    def test_custom_deposit_rate(self, client: TestClient, headers: dict):
        """自定义定金比例 50%。"""
        total = 1000000
        order = create_test_order(client, headers, total_fen=total, deposit_rate=0.50)
        assert abs(order["deposit_fen"] - 500000) <= 1

    def test_missing_tenant_id_returns_400(self, client: TestClient):
        """缺少 X-Tenant-ID header 应返回 400。"""
        resp = client.post(
            "/api/v1/trade/banquet/orders",
            json={
                "store_id": STORE_ID,
                "contact_name": "测试",
                "contact_phone": "13800000001",
                "banquet_date": "2026-06-01",
                "banquet_time": "18:00",
                "guest_count": 10,
                "total_fen": 100000,
            },
        )
        assert resp.status_code == 400


# ─── 2. 支付定金流程 ──────────────────────────────────────────────────────────


class TestPayDepositFlow:
    def test_pay_exact_deposit(self, client: TestClient, headers: dict):
        """支付精确定金金额 → deposit_status=paid, payment_status=deposit_paid。"""
        order = create_test_order(client, headers, total_fen=500000, deposit_rate=0.30)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={
                "payment_method": "wechat",
                "amount_fen": deposit_fen,
                "transaction_id": "WX_TEST_001",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        updated_order = body["data"]["order"]
        assert updated_order["deposit_status"] == "paid"
        assert updated_order["payment_status"] == "deposit_paid"
        assert updated_order["balance_status"] == "unpaid"

    def test_pay_more_than_deposit_not_full(self, client: TestClient, headers: dict):
        """多付定金但不足总额 → deposit_paid，尾款仍为 unpaid。"""
        order = create_test_order(client, headers, total_fen=1000000, deposit_rate=0.30)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={
                "payment_method": "cash",
                "amount_fen": deposit_fen + 1000,  # 多付 10 元，但不足总额
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["order"]["payment_status"] == "deposit_paid"

    def test_pay_full_amount_at_deposit_step(self, client: TestClient, headers: dict):
        """一次性付清总额（定金阶段直接全款）→ payment_status=fully_paid。"""
        order = create_test_order(client, headers, total_fen=300000)
        order_id = order["id"]
        total_fen = order["total_fen"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={
                "payment_method": "transfer",
                "amount_fen": total_fen,  # 全款
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["order"]["payment_status"] == "fully_paid"
        assert body["data"]["order"]["balance_status"] == "paid"

    def test_underpay_deposit_returns_400(self, client: TestClient, headers: dict):
        """少付定金 → 400。"""
        order = create_test_order(client, headers, total_fen=500000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={
                "payment_method": "wechat",
                "amount_fen": deposit_fen - 1,  # 少付 1 分
            },
            headers=headers,
        )
        assert resp.status_code == 400, f"期望 400，实际 {resp.status_code}"

    def test_duplicate_deposit_returns_400(self, client: TestClient, headers: dict):
        """重复收定金 → 400。"""
        order = create_test_order(client, headers, total_fen=500000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]

        # 第一次
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        # 第二次
        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        assert resp.status_code == 400


# ─── 3. 尾款前置检查 ──────────────────────────────────────────────────────────


class TestPayBalanceRequiresDeposit:
    def test_balance_fails_when_deposit_unpaid(self, client: TestClient, headers: dict):
        """定金未支付时尝试支付尾款 → 400。"""
        order = create_test_order(client, headers, total_fen=800000)
        order_id = order["id"]
        balance_fen = order["balance_fen"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={
                "payment_method": "wechat",
                "amount_fen": balance_fen,
            },
            headers=headers,
        )
        assert resp.status_code == 400, f"定金未付时应拒绝收尾款（期望 400，实际 {resp.status_code}）"

    def test_balance_succeeds_after_deposit(self, client: TestClient, headers: dict):
        """定金已付后支付尾款 → 200，payment_status=fully_paid。"""
        order = create_test_order(client, headers, total_fen=800000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]
        balance_fen = order["balance_fen"]

        # 先付定金
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        # 再付尾款
        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "card", "amount_fen": balance_fen},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["order"]["payment_status"] == "fully_paid"

    def test_underpay_balance_returns_400(self, client: TestClient, headers: dict):
        """少付尾款 → 400。"""
        order = create_test_order(client, headers, total_fen=600000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]
        balance_fen = order["balance_fen"]

        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "wechat", "amount_fen": balance_fen - 100},
            headers=headers,
        )
        assert resp.status_code == 400


# ─── 4. 完整支付流程 ──────────────────────────────────────────────────────────


class TestFullPaymentFlow:
    def test_create_pay_deposit_pay_balance_fully_paid(self, client: TestClient, headers: dict):
        """完整流程：创建 → 付定金 → 付尾款 → fully_paid。"""
        # Step 1: 创建
        order = create_test_order(client, headers, total_fen=1000000, deposit_rate=0.30)
        order_id = order["id"]
        assert order["payment_status"] == "unpaid"

        # Step 2: 付定金
        deposit_fen = order["deposit_fen"]
        r1 = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        assert r1.status_code == 200
        assert r1.json()["data"]["order"]["payment_status"] == "deposit_paid"

        # Step 3: 付尾款
        balance_fen = order["balance_fen"]
        r2 = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "transfer", "amount_fen": balance_fen},
            headers=headers,
        )
        assert r2.status_code == 200
        final_order = r2.json()["data"]["order"]
        assert final_order["payment_status"] == "fully_paid"
        assert final_order["deposit_status"] == "paid"
        assert final_order["balance_status"] == "paid"

    def test_full_flow_payment_records(self, client: TestClient, headers: dict):
        """完整流程后支付记录应有 2 条：定金 + 尾款。"""
        order = create_test_order(client, headers, total_fen=750000)
        order_id = order["id"]

        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": order["deposit_fen"]},
            headers=headers,
        )
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "card", "amount_fen": order["balance_fen"]},
            headers=headers,
        )

        # 查询订单详情验证支付记录
        detail_resp = client.get(
            f"/api/v1/trade/banquet/orders/{order_id}",
            headers=headers,
        )
        assert detail_resp.status_code == 200
        detail = detail_resp.json()["data"]
        payments = detail.get("payments", [])
        assert len(payments) == 2, f"期望 2 条支付记录，实际 {len(payments)} 条"
        stages = {p["payment_stage"] for p in payments}
        assert "deposit" in stages
        assert "balance" in stages


# ─── 5. 退定金逻辑 ──────────────────────────────────────────────────────────


class TestRefundDepositOnly:
    def test_refund_deposit_when_deposit_paid_balance_unpaid(self, client: TestClient, headers: dict):
        """deposit_paid 且 balance_status=unpaid 时可退定金。"""
        order = create_test_order(client, headers, total_fen=500000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]

        # 付定金
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )

        # 退定金
        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/refund",
            json={
                "refund_type": "deposit",
                "reason": "顾客临时取消",
                "amount_fen": deposit_fen,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["order"]["deposit_status"] == "unpaid"
        assert body["data"]["order"]["payment_status"] == "refunded"

    def test_cannot_refund_deposit_only_when_fully_paid(self, client: TestClient, headers: dict):
        """已全额支付时禁止仅退定金（应走 full 退款）→ 400。"""
        order = create_test_order(client, headers, total_fen=500000)
        order_id = order["id"]
        deposit_fen = order["deposit_fen"]
        balance_fen = order["balance_fen"]

        # 付定金
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": deposit_fen},
            headers=headers,
        )
        # 付尾款
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "wechat", "amount_fen": balance_fen},
            headers=headers,
        )

        # 尝试仅退定金 → 应被拒绝
        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/refund",
            json={
                "refund_type": "deposit",
                "reason": "测试：不允许已全额支付后仅退定金",
                "amount_fen": deposit_fen,
            },
            headers=headers,
        )
        assert resp.status_code == 400, f"全额支付后不允许仅退定金（期望 400，实际 {resp.status_code}）"

    def test_full_refund_when_fully_paid(self, client: TestClient, headers: dict):
        """fully_paid 状态可申请全额退款 → payment_status=refunded。"""
        order = create_test_order(client, headers, total_fen=600000)
        order_id = order["id"]

        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-deposit",
            json={"payment_method": "wechat", "amount_fen": order["deposit_fen"]},
            headers=headers,
        )
        client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/pay-balance",
            json={"payment_method": "card", "amount_fen": order["balance_fen"]},
            headers=headers,
        )

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/refund",
            json={
                "refund_type": "full",
                "reason": "活动取消，全额退款",
                "amount_fen": order["total_fen"],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["order"]["payment_status"] == "refunded"
        assert body["data"]["order"]["deposit_status"] == "unpaid"
        assert body["data"]["order"]["balance_status"] == "unpaid"

    def test_cannot_refund_deposit_when_deposit_not_paid(self, client: TestClient, headers: dict):
        """定金未付时申请退定金 → 400。"""
        order = create_test_order(client, headers, total_fen=400000)
        order_id = order["id"]

        resp = client.post(
            f"/api/v1/trade/banquet/orders/{order_id}/refund",
            json={
                "refund_type": "deposit",
                "reason": "定金未付，不可退",
                "amount_fen": order["deposit_fen"],
            },
            headers=headers,
        )
        assert resp.status_code == 400
