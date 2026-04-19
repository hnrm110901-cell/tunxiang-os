"""财务分析服务 (D5) 测试 — API 冒烟 + 服务逻辑单元测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 注册 analytics_routes（若 main.py 尚未注册，在此补充）
from api.analytics_routes import router as analytics_router
from fastapi.testclient import TestClient
from main import app

if not any(r.prefix == "/api/v1/finance/analytics" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(analytics_router)

client = TestClient(app)


# ── API 冒烟测试 ──────────────────────────────────────────────


class TestRevenueCompositionAPI:
    def test_revenue_composition_ok(self):
        r = client.get(
            "/api/v1/finance/analytics/revenue-composition",
            params={"store_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "by_source" in data["data"]
        assert "by_payment" in data["data"]
        assert "total_revenue_fen" in data["data"]

    def test_revenue_composition_requires_params(self):
        r = client.get("/api/v1/finance/analytics/revenue-composition")
        assert r.status_code == 422


class TestDiscountStructureAPI:
    def test_discount_structure_ok(self):
        r = client.get(
            "/api/v1/finance/analytics/discount-structure",
            params={"store_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "total_discount_fen" in data["data"]
        assert "discount_rate" in data["data"]
        assert "by_type" in data["data"]

    def test_discount_structure_response_shape(self):
        r = client.get(
            "/api/v1/finance/analytics/discount-structure",
            params={"store_id": "s1", "start_date": "2026-03-01", "end_date": "2026-03-27"},
        )
        data = r.json()["data"]
        assert "gross_amount_fen" in data
        assert "net_amount_fen" in data
        assert "gift_cost_fen" in data


class TestCouponCostAPI:
    def test_coupon_cost_ok(self):
        r = client.get(
            "/api/v1/finance/analytics/coupon-cost",
            params={"store_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "total_coupon_cost_fen" in data["data"]
        assert "roi" in data["data"]
        assert "by_campaign" in data["data"]


class TestStoreProfitAPI:
    def test_store_profit_ok(self):
        r = client.get(
            "/api/v1/finance/analytics/store-profit",
            params={"store_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "revenue_fen" in data["data"]
        assert "food_cost_fen" in data["data"]
        assert "labor_cost_fen" in data["data"]
        assert "profit_fen" in data["data"]
        assert "profit_rate" in data["data"]

    def test_store_profit_includes_margin(self):
        r = client.get(
            "/api/v1/finance/analytics/store-profit",
            params={"store_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        data = r.json()["data"]
        assert "gross_profit_fen" in data
        assert "gross_margin" in data


class TestAuditViewAPI:
    def test_audit_view_ok(self):
        r = client.get(
            "/api/v1/finance/analytics/audit-view",
            params={"store_id": "s1", "date": "2026-03-27"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["audit_date"] == "2026-03-27"
        assert "summary" in data["data"]
        assert "returns" in data["data"]
        assert "gifts" in data["data"]
        assert "alerts" in data["data"]
        assert "hourly_breakdown" in data["data"]

    def test_audit_view_requires_date(self):
        r = client.get(
            "/api/v1/finance/analytics/audit-view",
            params={"store_id": "s1"},
        )
        assert r.status_code == 422


# ── 服务层单元测试（纯函数逻辑） ───────────────────────────────


class TestSafeRatio:
    def test_zero_denominator(self):
        from services.finance_analytics import _safe_ratio

        assert _safe_ratio(100, 0) == 0.0
        assert _safe_ratio(0, 0) == 0.0

    def test_normal_ratio(self):
        from services.finance_analytics import _safe_ratio

        assert _safe_ratio(1, 4) == 0.25
        assert _safe_ratio(350, 1000) == 0.35

    def test_profit_rate_calculation(self):
        """验证利润率计算：profit / revenue"""
        from services.finance_analytics import _safe_ratio

        revenue = 100000  # 1000元
        food_cost = 35000
        labor = 25000
        rent = 10000
        other = 5000
        profit = revenue - food_cost - labor - rent - other  # 25000
        profit_rate = _safe_ratio(profit, revenue)
        assert profit_rate == 0.25
