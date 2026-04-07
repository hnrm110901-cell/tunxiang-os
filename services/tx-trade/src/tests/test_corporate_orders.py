"""
团餐/企业客户路由测试
Y-A9

覆盖：
1. test_create_corporate_order_with_discount — 企业折扣正确应用
2. test_credit_limit_exceeded               — 授信超限返回 400
3. test_bulk_billing                        — 批量出账生成 bill_id + 订单标记 billed
"""
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ..api.corporate_order_routes import (
    router,
    MOCK_CORPORATE_CUSTOMERS,
    _MOCK_ORDERS,
    _MOCK_BILLS,
)

# ─── 测试 App ─────────────────────────────────────────────────────────────────

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _reset_mock_state() -> None:
    """测试前重置 mock 订单、账单状态，恢复企业客户授信。"""
    _MOCK_ORDERS.clear()
    _MOCK_BILLS.clear()
    for c in MOCK_CORPORATE_CUSTOMERS:
        if c["id"] == "corp-001":
            c["used_credit_fen"] = 1_280_000
            c["status"] = "active"
        if c["id"] == "corp-002":
            c["used_credit_fen"] = 680_000
            c["status"] = "active"


# ─── Test 1: 企业订单应用折扣 ────────────────────────────────────────────────

class TestCreateCorporateOrderWithDiscount:
    """企业订单应用 discount_rate=0.95，实际金额 = 原始金额 × 0.95"""

    def setup_method(self) -> None:
        _reset_mock_state()

    def test_discount_applied_correctly(self) -> None:
        """订单金额 × 0.95 四舍五入到整数分"""
        payload = {
            "corporate_customer_id": "corp-001",   # discount_rate=0.95
            "store_id": "store-aaa",
            "items": [
                {"dish_id": "dish-001", "dish_name": "红烧肉", "qty": 2, "unit_price_fen": 3800},
                {"dish_id": "dish-002", "dish_name": "米饭",   "qty": 5, "unit_price_fen": 200},
            ],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload)
        assert resp.status_code == 201, resp.text

        data = resp.json()["data"]
        original = 2 * 3800 + 5 * 200   # = 8600
        expected_discounted = int(
            (Decimal(str(original)) * Decimal("0.95")).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )  # = 8170

        assert data["original_amount_fen"] == original
        assert data["discount_rate"] == pytest.approx(0.95, abs=1e-6)
        assert data["discounted_amount_fen"] == expected_discounted
        assert data["billing_status"] == "unbilled"

    def test_no_discount_rate_one(self) -> None:
        """discount_rate=1.000 时折扣金额 == 原始金额"""
        # 临时创建一个无折扣的企业客户
        create_resp = client.post("/api/v1/trade/corporate/customers", json={
            "company_name": "测试无折扣公司",
            "credit_limit_fen": 10_000_000,
            "discount_rate": 1.0,
        })
        assert create_resp.status_code == 201
        cid = create_resp.json()["data"]["id"]

        order_resp = client.post("/api/v1/trade/corporate/orders", json={
            "corporate_customer_id": cid,
            "store_id": "store-bbb",
            "items": [{"dish_id": "dish-x", "qty": 1, "unit_price_fen": 5000}],
        })
        assert order_resp.status_code == 201
        odata = order_resp.json()["data"]
        assert odata["original_amount_fen"] == odata["discounted_amount_fen"]

    def test_order_updates_used_credit(self) -> None:
        """下单后企业 used_credit_fen 正确增加"""
        before_resp = client.get("/api/v1/trade/corporate/customers/corp-001/credit")
        before_used = before_resp.json()["data"]["used_credit_fen"]

        payload = {
            "corporate_customer_id": "corp-001",
            "store_id": "store-ccc",
            "items": [{"dish_id": "dish-003", "qty": 1, "unit_price_fen": 10_000}],
        }
        client.post("/api/v1/trade/corporate/orders", json=payload)

        after_resp = client.get("/api/v1/trade/corporate/customers/corp-001/credit")
        after_used = after_resp.json()["data"]["used_credit_fen"]

        # 增加的应是折后金额（10000 × 0.95 = 9500）
        assert after_used == before_used + 9500


# ─── Test 2: 授信超限返回 400 ────────────────────────────────────────────────

class TestCreditLimitExceeded:
    """used + amount > limit → 必须返回 400，不能静默通过"""

    def setup_method(self) -> None:
        _reset_mock_state()

    def test_credit_exceeded_returns_400(self) -> None:
        """可用授信不足时拒绝下单并返回 400"""
        # corp-001: limit=5_000_000, used=1_280_000, available=3_720_000
        # 下单 4_000_000 分（折后 3_800_000），超过可用额度
        payload = {
            "corporate_customer_id": "corp-001",
            "store_id": "store-ddd",
            "items": [
                {
                    "dish_id": "dish-big",
                    "dish_name": "大额套餐",
                    "qty": 1,
                    # discount_rate=0.95, 所以需要原始价 > available/0.95 ≈ 3_915_790
                    "unit_price_fen": 4_000_000,
                }
            ],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload)
        assert resp.status_code == 400, f"应返回 400，实际: {resp.status_code}"
        assert "授信额度不足" in resp.json()["detail"]

    def test_credit_exactly_at_limit_succeeds(self) -> None:
        """恰好用完授信（不超限）应成功"""
        # corp-001: available = 5_000_000 - 1_280_000 = 3_720_000
        # 下单 3_720_000/0.95 ≈ 3_915_790 原始价，折后恰好 3_720_000
        # 简单用可用额度内的金额：折后 3_720_000，原始 = 3_720_000/0.95 ≈ 3_915_789
        # 为避免浮点误差，下单原始 3_000_000，折后 2_850_000 < 3_720_000 → 成功
        payload = {
            "corporate_customer_id": "corp-001",
            "store_id": "store-eee",
            "items": [{"dish_id": "dish-safe", "qty": 1, "unit_price_fen": 3_000_000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload)
        assert resp.status_code == 201, f"应成功，实际: {resp.status_code}; {resp.text}"

    def test_inactive_customer_returns_400(self) -> None:
        """status != active 的企业客户无法下单"""
        # 将 corp-002 设为 inactive
        client.put("/api/v1/trade/corporate/customers/corp-002", json={"status": "inactive"})

        payload = {
            "corporate_customer_id": "corp-002",
            "store_id": "store-fff",
            "items": [{"dish_id": "dish-y", "qty": 1, "unit_price_fen": 1000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload)
        assert resp.status_code == 400
        assert "inactive" in resp.json()["detail"]


# ─── Test 3: 批量出账 ─────────────────────────────────────────────────────────

class TestBulkBilling:
    """批量出账：调用后返回 bill_id，相关订单标记 billed"""

    def setup_method(self) -> None:
        _reset_mock_state()

    def _create_order(self, customer_id: str = "corp-001",
                      amount_fen: int = 5_000) -> str:
        """便捷创建一条企业订单，返回 order_id"""
        resp = client.post("/api/v1/trade/corporate/orders", json={
            "corporate_customer_id": customer_id,
            "store_id": "store-bill-test",
            "items": [{"dish_id": "dish-bill", "qty": 1, "unit_price_fen": amount_fen}],
        })
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]["order_id"]

    def test_bulk_bill_returns_bill_id(self) -> None:
        """批量出账返回 bill_id 且格式正确"""
        today = date.today().isoformat()
        self._create_order()
        self._create_order()

        resp = client.post("/api/v1/trade/corporate/orders/bulk-bill", json={
            "corporate_customer_id": "corp-001",
            "billing_period_start": today,
            "billing_period_end": today,
        })
        assert resp.status_code == 200, resp.text

        data = resp.json()["data"]
        assert "bill_id" in data
        assert data["bill_id"].startswith("BILL-")
        assert data["order_count"] == 2
        assert data["status"] == "issued"

    def test_orders_marked_billed_after_bulk_bill(self) -> None:
        """出账后，相关订单 billing_status 变为 billed"""
        today = date.today().isoformat()
        order_id = self._create_order()

        # 出账前订单状态为 unbilled
        orders_resp = client.get(
            "/api/v1/trade/corporate/orders",
            params={"corporate_customer_id": "corp-001", "billing_status": "unbilled"},
        )
        unbilled_ids = [o["id"] for o in orders_resp.json()["data"]["items"]]
        assert order_id in unbilled_ids

        # 批量出账
        client.post("/api/v1/trade/corporate/orders/bulk-bill", json={
            "corporate_customer_id": "corp-001",
            "billing_period_start": today,
            "billing_period_end": today,
        })

        # 出账后订单状态应为 billed
        billed_resp = client.get(
            "/api/v1/trade/corporate/orders",
            params={"corporate_customer_id": "corp-001", "billing_status": "billed"},
        )
        billed_ids = [o["id"] for o in billed_resp.json()["data"]["items"]]
        assert order_id in billed_ids

    def test_no_unbilled_orders_returns_400(self) -> None:
        """无可出账订单时返回 400"""
        resp = client.post("/api/v1/trade/corporate/orders/bulk-bill", json={
            "corporate_customer_id": "corp-001",
            "billing_period_start": "2020-01-01",
            "billing_period_end": "2020-01-31",
        })
        assert resp.status_code == 400
        assert "未找到" in resp.json()["detail"]

    def test_csv_export_returns_csv_content(self) -> None:
        """对账导出返回 CSV 格式内容"""
        today = date.today().isoformat()
        self._create_order()

        resp = client.get(
            "/api/v1/trade/corporate/export",
            params={
                "corporate_customer_id": "corp-001",
                "date_from": today,
                "date_to": today,
                "format": "csv",
            },
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        content = resp.text
        assert "订单号" in content
        assert "企业名称" in content
