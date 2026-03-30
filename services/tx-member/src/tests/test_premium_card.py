"""超级年卡测试 — API 冒烟 + 服务逻辑单元测试

覆盖场景：
1. 年卡方案列表
2. 购买年卡 (正常/无效plan_id)
3. 权益清单
4. 权益使用情况
5. 续费
6. 赠送年卡 (正常/无效手机号)
7. 年卡常量校验
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

from api.premium_card_routes import router as premium_router

if not any(r.prefix == "/api/v1/member/premium" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(premium_router)

client = TestClient(app)

TENANT_HEADER = {"X-Tenant-ID": "test-tenant-001"}


# ── 1. 年卡方案列表 ──────────────────────────────────────────

class TestListPlans:
    def test_list_annual_plans(self):
        r = client.get("/api/v1/member/premium/plans", headers=TENANT_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        plans = data["data"]["plans"]
        assert len(plans) == 3
        plan_ids = [p["plan_id"] for p in plans]
        assert "silver" in plan_ids
        assert "gold" in plan_ids
        assert "diamond" in plan_ids

    def test_plan_prices(self):
        r = client.get("/api/v1/member/premium/plans", headers=TENANT_HEADER)
        plans = {p["plan_id"]: p for p in r.json()["data"]["plans"]}
        assert plans["silver"]["price_fen"] == 69800
        assert plans["gold"]["price_fen"] == 129800
        assert plans["diamond"]["price_fen"] == 299800


# ── 2. 购买年卡 ──────────────────────────────────────────────

class TestPurchaseCard:
    def test_purchase_ok(self):
        r = client.post(
            "/api/v1/member/premium/purchase",
            json={
                "customer_id": "cust-001",
                "plan_id": "gold",
                "payment_id": "pay-001",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["customer_id"] == "cust-001"
        assert data["data"]["plan_id"] == "gold"

    def test_purchase_missing_payment_id(self):
        r = client.post(
            "/api/v1/member/premium/purchase",
            json={
                "customer_id": "cust-001",
                "plan_id": "silver",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422  # Pydantic 校验


# ── 3. 权益清单 ──────────────────────────────────────────────

class TestCardBenefits:
    def test_get_benefits(self):
        r = client.get(
            "/api/v1/member/premium/cards/card-001/benefits",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "benefits" in data["data"]
        assert "days_remaining" in data["data"]


# ── 4. 权益使用情况 ──────────────────────────────────────────

class TestBenefitUsage:
    def test_check_usage(self):
        r = client.get(
            "/api/v1/member/premium/cards/card-001/usage",
            params={"benefit_type": "free_dish_monthly"},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["benefit_type"] == "free_dish_monthly"
        assert "total_quota" in data["data"]
        assert "used" in data["data"]
        assert "remaining" in data["data"]

    def test_check_usage_missing_type(self):
        r = client.get(
            "/api/v1/member/premium/cards/card-001/usage",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422  # Query 参数必填


# ── 5. 续费 ──────────────────────────────────────────────────

class TestRenewCard:
    def test_renew_ok(self):
        r = client.post(
            "/api/v1/member/premium/cards/card-001/renew",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["renewed"] is True


# ── 6. 赠送年卡 ──────────────────────────────────────────────

class TestGiftCard:
    def test_gift_ok(self):
        r = client.post(
            "/api/v1/member/premium/gift",
            json={
                "sender_id": "cust-001",
                "receiver_phone": "13800138000",
                "plan_id": "silver",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["sender_id"] == "cust-001"
        assert data["data"]["receiver_phone"] == "13800138000"

    def test_gift_invalid_phone(self):
        r = client.post(
            "/api/v1/member/premium/gift",
            json={
                "sender_id": "cust-001",
                "receiver_phone": "123",
                "plan_id": "gold",
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422  # Pydantic 校验手机号长度


# ── 7. 年卡常量校验 ──────────────────────────────────────────

class TestAnnualPlanConstants:
    def test_all_plans_have_benefits(self):
        from services.premium_card import ANNUAL_PLANS
        for plan_id, plan in ANNUAL_PLANS.items():
            assert "benefits" in plan, f"{plan_id} missing benefits"
            assert len(plan["benefits"]) > 0, f"{plan_id} has empty benefits"

    def test_all_plans_have_correct_duration(self):
        from services.premium_card import ANNUAL_PLANS
        for plan_id, plan in ANNUAL_PLANS.items():
            assert plan["duration_days"] == 365, f"{plan_id} duration != 365"

    def test_diamond_has_most_benefits(self):
        from services.premium_card import ANNUAL_PLANS
        silver_count = len(ANNUAL_PLANS["silver"]["benefits"])
        gold_count = len(ANNUAL_PLANS["gold"]["benefits"])
        diamond_count = len(ANNUAL_PLANS["diamond"]["benefits"])
        assert diamond_count > gold_count > silver_count
