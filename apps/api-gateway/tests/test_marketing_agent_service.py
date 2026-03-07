"""
测试 MarketingAgentService 核心方法：
- 客群分群逻辑（_determine_segment）
- 流失风险计算（_predict_churn_risk）
- 顾客价值评分（_calculate_customer_value）
- 口味向量化（_vectorize_taste_preference）
- 批量客群分布（get_store_segment_summary）
- 流失风险客户列表（get_at_risk_customers）
"""
import os
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── env setup must happen before src imports ──────────────────────────────────
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/zhilian")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.services.marketing_agent_service import (  # noqa: E402
    CustomerSegment,
    MarketingAgentService,
    CouponStrategy,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def make_service() -> MarketingAgentService:
    return MarketingAgentService(db=MagicMock())


# ── _determine_segment ────────────────────────────────────────────────────────

class TestDetermineSegment:
    def setup_method(self):
        self.svc = make_service()

    def test_high_value(self):
        seg = self.svc._determine_segment(value_score=80, churn_risk=0.1)
        assert seg == CustomerSegment.HIGH_VALUE

    def test_potential(self):
        seg = self.svc._determine_segment(value_score=55, churn_risk=0.2)
        assert seg == CustomerSegment.POTENTIAL

    def test_at_risk(self):
        seg = self.svc._determine_segment(value_score=45, churn_risk=0.7)
        assert seg == CustomerSegment.AT_RISK

    def test_lost(self):
        seg = self.svc._determine_segment(value_score=10, churn_risk=0.95)
        assert seg == CustomerSegment.LOST

    def test_new_customer(self):
        seg = self.svc._determine_segment(value_score=20, churn_risk=0.15)
        assert seg == CustomerSegment.NEW

    def test_boundary_high_value_churn_too_high(self):
        # value high but churn >= 0.3 → not HIGH_VALUE
        seg = self.svc._determine_segment(value_score=75, churn_risk=0.5)
        assert seg != CustomerSegment.HIGH_VALUE


# ── _vectorize_taste_preference (unit, mock DB) ───────────────────────────────

class TestVectorizeTastePreference:
    def setup_method(self):
        self.svc = make_service()

    def test_returns_5d_vector(self):
        # mock empty DB → default vector
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

            vector = asyncio.run(self.svc._vectorize_taste_preference("13800000001"))

        assert len(vector) == 5
        assert all(isinstance(v, float) for v in vector)
        assert all(0.0 <= v <= 1.0 for v in vector)

    def test_default_vector_when_no_orders(self):
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

            vector = asyncio.run(self.svc._vectorize_taste_preference("13800000001"))

        assert vector == [0.5, 0.2, 0.3, 0.6, 0.2]


# ── generate_coupon_strategy ──────────────────────────────────────────────────

class TestGenerateCouponStrategy:
    def setup_method(self):
        self.svc = make_service()

    def _run(self, scenario: str) -> CouponStrategy:
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
            return asyncio.run(self.svc.generate_coupon_strategy(scenario, "STORE001"))

    def test_traffic_decline_gives_满减(self):
        strat = self._run("traffic_decline")
        assert strat.coupon_type == "满减券"
        assert strat.target_segment == CustomerSegment.AT_RISK
        assert strat.amount > 0

    def test_new_product_launch_gives_代金(self):
        strat = self._run("new_product_launch")
        assert strat.coupon_type == "代金券"
        assert strat.target_segment == CustomerSegment.HIGH_VALUE
        assert strat.threshold is None

    def test_member_day_gives_折扣(self):
        strat = self._run("member_day")
        assert strat.coupon_type == "折扣券"
        assert strat.target_segment == CustomerSegment.POTENTIAL

    def test_default_scenario(self):
        strat = self._run("unknown_scenario")
        assert strat.coupon_type == "满减券"
        assert strat.target_segment == CustomerSegment.NEW

    def test_expected_roi_positive(self):
        for scenario in ["traffic_decline", "new_product_launch", "member_day"]:
            strat = self._run(scenario)
            assert strat.expected_roi > 0
            assert 0.0 < strat.expected_conversion < 1.0


# ── get_store_segment_summary ─────────────────────────────────────────────────

class TestGetStoreSegmentSummary:
    def setup_method(self):
        self.svc = make_service()

    def _make_row(self, phone: str, order_count: int, total_amount: int, days_ago: int):
        row = MagicMock()
        row.customer_phone = phone
        row.order_count = order_count
        row.total_amount = total_amount
        row.last_order_time = datetime.now() - timedelta(days=days_ago)
        return row

    def test_returns_all_segment_keys(self):
        rows = [self._make_row("138", 10, 50000, 3)]  # recent active → high_value or potential
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))

            result = asyncio.run(self.svc.get_store_segment_summary("STORE001"))

        assert result["store_id"] == "STORE001"
        assert result["total_customers"] == 1
        for seg in ["high_value", "potential", "at_risk", "lost", "new"]:
            assert seg in result["segments"]
        assert sum(result["segments"].values()) == 1

    def test_empty_store(self):
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

            result = asyncio.run(self.svc.get_store_segment_summary("EMPTY_STORE"))

        assert result["total_customers"] == 0
        assert all(v == 0 for v in result["segments"].values())

    def test_pct_sums_to_100_single_customer(self):
        rows = [self._make_row("139", 5, 20000, 5)]
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))

            result = asyncio.run(self.svc.get_store_segment_summary("STORE001"))

        assert sum(result["segments_pct"].values()) == pytest.approx(100.0, abs=0.2)

    def test_at_risk_customer_counted(self):
        # 45 days ago → churn_risk=0.6; 25 orders + 5000 yuan → value_score≈53 > 40 → AT_RISK
        rows = [self._make_row("137", 25, 500000, 45)]  # 500000 cents = 5000 yuan
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))

            result = asyncio.run(self.svc.get_store_segment_summary("STORE001"))

        assert result["segments"]["at_risk"] == 1


# ── get_at_risk_customers ─────────────────────────────────────────────────────

class TestGetAtRiskCustomers:
    def setup_method(self):
        self.svc = make_service()

    def _make_row(self, phone: str, name: str, order_count: int, total_amount: int, days_ago: int):
        row = MagicMock()
        row.customer_phone = phone
        row.customer_name = name
        row.order_count = order_count
        row.total_amount = total_amount
        row.last_order_time = datetime.now() - timedelta(days=days_ago)
        return row

    def _run(self, rows, risk_threshold=0.5):
        with patch("src.services.marketing_agent_service.get_db_session") as mock_ctx:
            session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
            return asyncio.run(self.svc.get_at_risk_customers("STORE001", limit=50, risk_threshold=risk_threshold))

    def test_empty_result_when_no_rows(self):
        result = self._run([])
        assert result == []

    def test_at_risk_customer_included(self):
        rows = [self._make_row("138", "张三", 3, 15000, 45)]
        result = self._run(rows)
        assert len(result) == 1
        assert result[0]["customer_phone"] == "138"
        assert result[0]["churn_risk"] == pytest.approx(0.6, abs=0.01)
        assert result[0]["segment"] == "at_risk"

    def test_lost_customer_included(self):
        rows = [self._make_row("139", "李四", 2, 8000, 90)]
        result = self._run(rows)
        assert len(result) == 1
        assert result[0]["churn_risk"] == pytest.approx(0.9, abs=0.01)
        assert result[0]["segment"] == "lost"
        assert result[0]["recommended_action"] == "重新激活营销"

    def test_sorted_by_risk_descending(self):
        rows = [
            self._make_row("111", "A", 5, 20000, 45),   # churn_risk=0.6
            self._make_row("222", "B", 2, 5000, 90),    # churn_risk=0.9
        ]
        result = self._run(rows)
        assert result[0]["churn_risk"] >= result[1]["churn_risk"]

    def test_threshold_filters_low_risk(self):
        rows = [self._make_row("111", "A", 5, 20000, 45)]  # churn_risk=0.6
        result = self._run(rows, risk_threshold=0.7)
        assert len(result) == 0  # 0.6 < 0.7 threshold → filtered out

    def test_yuan_field_correct(self):
        rows = [self._make_row("138", "张三", 3, 15000, 45)]
        result = self._run(rows)
        assert result[0]["total_amount_yuan"] == pytest.approx(150.0, abs=0.01)

    def test_days_since_calculated(self):
        rows = [self._make_row("138", "张三", 3, 15000, 45)]
        result = self._run(rows)
        assert result[0]["days_since_last_order"] == pytest.approx(45, abs=1)
