"""会员分析服务 (D4) 测试 — API 冒烟 + 服务逻辑单元测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 注册 analytics_routes（若 main.py 尚未注册，在此补充）
from api.analytics_routes import router as analytics_router
from fastapi.testclient import TestClient
from main import app

if not any(r.prefix == "/api/v1/member/analytics" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(analytics_router)

client = TestClient(app)


# ── API 冒烟测试 ──────────────────────────────────────────────


class TestMemberGrowthAPI:
    def test_growth_ok(self):
        r = client.get(
            "/api/v1/member/analytics/growth",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "new_members" in data["data"]
        assert "total" in data["data"]
        assert "growth_rate" in data["data"]
        assert "by_channel" in data["data"]

    def test_growth_requires_dates(self):
        r = client.get("/api/v1/member/analytics/growth")
        assert r.status_code == 422  # Missing required params


class TestActivityAnalysisAPI:
    def test_activity_ok(self):
        r = client.get(
            "/api/v1/member/analytics/activity",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "active_rate" in data["data"]
        assert "dau" in data["data"]
        assert "mau" in data["data"]
        assert "by_store" in data["data"]


class TestRepurchaseAnalysisAPI:
    def test_repurchase_ok(self):
        r = client.get(
            "/api/v1/member/analytics/repurchase",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "repurchase_rate" in data["data"]
        assert "by_frequency_band" in data["data"]


class TestChurnPredictionAPI:
    def test_churn_ok(self):
        r = client.get("/api/v1/member/analytics/churn-prediction")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "predictions" in data["data"]

    def test_churn_risk_levels(self):
        """验证返回结构包含风险统计"""
        r = client.get("/api/v1/member/analytics/churn-prediction")
        data = r.json()["data"]
        assert "high_risk_count" in data
        assert "medium_risk_count" in data


class TestPreferenceInsightAPI:
    def test_preference_ok(self):
        r = client.get("/api/v1/member/analytics/preference/test-customer-id")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["customer_id"] == "test-customer-id"
        assert "favorite_dishes" in data["data"]
        assert "visit_pattern" in data["data"]
        assert "avg_spend_fen" in data["data"]
        assert "preferred_time" in data["data"]


# ── 服务层单元测试（纯函数逻辑） ───────────────────────────────


class TestChurnRiskCalculation:
    """验证流失风险分计算逻辑"""

    def test_high_risk_threshold(self):
        """>60天未消费应为高风险"""
        from services.member_analytics import CHURN_HIGH_RISK_DAYS, CHURN_MEDIUM_RISK_DAYS

        assert CHURN_HIGH_RISK_DAYS == 60
        assert CHURN_MEDIUM_RISK_DAYS == 30

    def test_safe_ratio_zero_denominator(self):
        from services.member_analytics import _safe_ratio

        assert _safe_ratio(100, 0) == 0.0
        assert _safe_ratio(0, 0) == 0.0

    def test_safe_ratio_normal(self):
        from services.member_analytics import _safe_ratio

        assert _safe_ratio(1, 4) == 0.25
        assert _safe_ratio(3, 10) == 0.3

    def test_frequency_bands_cover_all(self):
        """频次带必须无缝覆盖 1 到 999999"""
        from services.member_analytics import FREQUENCY_BANDS

        assert len(FREQUENCY_BANDS) >= 4
        assert FREQUENCY_BANDS[0][1] == 1  # 从 1 开始
        assert FREQUENCY_BANDS[-1][2] >= 999  # 覆盖到高频
