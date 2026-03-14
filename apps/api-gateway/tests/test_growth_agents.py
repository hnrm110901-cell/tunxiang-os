"""
Sprint 4 单元测试 — 裂变引擎 + FloorAgent + MenuAgent + 增收月报

测试纯函数 + 服务方法（mock DB）
"""
import os
for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock


# ══════════════════════════════════════════════════════════════════
# 裂变引擎 (ReferralEngine)
# ══════════════════════════════════════════════════════════════════

from src.services.referral_engine_service import (
    compute_k_factor,
    classify_referral_scene,
    estimate_referral_value,
    ReferralEngineService,
)


class TestComputeKFactor:
    """病毒系数 K = 邀请数 × 转化率"""

    def test_positive(self):
        assert compute_k_factor(10, 0.3) == 3.0

    def test_self_growth(self):
        k = compute_k_factor(5, 0.3)
        assert k == 1.5  # K > 1 自增长

    def test_zero_invites(self):
        assert compute_k_factor(0, 0.5) == 0.0

    def test_zero_conversion(self):
        assert compute_k_factor(10, 0.0) == 0.0


class TestClassifyReferralScene:
    """裂变场景识别"""

    def test_banquet_10_plus(self):
        result = classify_referral_scene(10)
        assert result["scene"] == "banquet"
        assert result["k_estimate"] == 2.5

    def test_birthday(self):
        result = classify_referral_scene(6, "张三生日宴")
        assert result["scene"] == "birthday"
        assert result["k_estimate"] == 2.0

    def test_business_dinner(self):
        result = classify_referral_scene(8, "李总")
        assert result["scene"] == "business_dinner"
        assert result["k_estimate"] == 1.5

    def test_fan_gathering(self):
        result = classify_referral_scene(6, "老王聚餐")
        assert result["scene"] == "fan_gathering"
        assert result["k_estimate"] == 1.8

    def test_regular_small(self):
        result = classify_referral_scene(4)
        assert result["scene"] == "regular"
        assert result["k_estimate"] == 0.0

    def test_birthday_keyword_shou(self):
        result = classify_referral_scene(6, "王奶奶寿宴")
        assert result["scene"] == "birthday"


class TestEstimateReferralValue:
    """裂变预期营收估算"""

    def test_positive_value(self):
        result = estimate_referral_value(200.0, 1.5, 10)
        assert result["expected_new_customers"] == 15.0
        # 15 × 200 × 0.8 = 2400
        assert result["expected_revenue_yuan"] == 2400.0

    def test_zero_k(self):
        result = estimate_referral_value(200.0, 0.0, 10)
        assert result["expected_new_customers"] == 0.0
        assert result["expected_revenue_yuan"] == 0.0


class TestReferralEngineService:

    @pytest.fixture
    def service(self):
        return ReferralEngineService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_top_referrers_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await service.get_top_referrers(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# FloorAgent 楼面智能
# ══════════════════════════════════════════════════════════════════

from src.services.floor_agent_service import (
    compute_turnover_rate,
    compute_seat_utilization,
    classify_table_efficiency,
    compute_wait_conversion,
    FloorAgentService,
)


class TestComputeTurnoverRate:
    """翻台率"""

    def test_normal(self):
        # 100 orders / (10 tables × 5 days) = 2.0
        assert compute_turnover_rate(100, 10, 5) == 2.0

    def test_zero_tables(self):
        assert compute_turnover_rate(100, 0, 5) == 0.0

    def test_zero_days(self):
        assert compute_turnover_rate(100, 10, 0) == 0.0

    def test_high_turnover(self):
        rate = compute_turnover_rate(300, 10, 5)
        assert rate == 6.0


class TestComputeSeatUtilization:
    """座位利用率"""

    def test_full(self):
        assert compute_seat_utilization(100, 100) == 1.0

    def test_half(self):
        assert compute_seat_utilization(50, 100) == 0.5

    def test_over_capacity_capped(self):
        assert compute_seat_utilization(150, 100) == 1.0

    def test_zero_capacity(self):
        assert compute_seat_utilization(50, 0) == 0.0


class TestClassifyTableEfficiency:
    """桌台效率分级"""

    def test_high(self):
        assert classify_table_efficiency(3.0, 60) == "high"

    def test_normal(self):
        assert classify_table_efficiency(2.0, 80) == "normal"

    def test_low_turnover(self):
        assert classify_table_efficiency(1.0, 60) == "low"

    def test_low_long_duration(self):
        assert classify_table_efficiency(2.0, 130) == "normal"

    def test_high_turnover_long_duration(self):
        # 翻台≥2.5 但用餐>70min → normal
        assert classify_table_efficiency(3.0, 80) == "normal"


class TestComputeWaitConversion:
    """等位转化率"""

    def test_full_conversion(self):
        assert compute_wait_conversion(10, 10) == 1.0

    def test_partial(self):
        assert compute_wait_conversion(10, 7) == 0.7

    def test_zero_waiting(self):
        assert compute_wait_conversion(0, 0) == 0.0


class TestFloorAgentService:

    @pytest.fixture
    def service(self):
        return FloorAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_hourly_heatmap_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_hourly_heatmap(mock_db, "S001")
        assert len(result) == 24
        assert all(h["orders"] == 0 for h in result)

    @pytest.mark.asyncio
    async def test_table_efficiency_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_table_efficiency(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# MenuAgent 菜品智能
# ══════════════════════════════════════════════════════════════════

from src.services.menu_agent_service import (
    classify_dish_star,
    compute_combo_affinity,
    estimate_margin_impact,
    MenuAgentService,
)


class TestClassifyDishStar:
    """BCG菜品矩阵"""

    def test_star(self):
        assert classify_dish_star(0.8, 0.7) == "star"

    def test_cash_cow(self):
        assert classify_dish_star(0.8, 0.4) == "cash_cow"

    def test_question(self):
        assert classify_dish_star(0.3, 0.7) == "question"

    def test_dog(self):
        assert classify_dish_star(0.3, 0.4) == "dog"

    def test_boundary_star(self):
        assert classify_dish_star(0.5, 0.6) == "star"

    def test_boundary_dog(self):
        assert classify_dish_star(0.49, 0.59) == "dog"


class TestComputeComboAffinity:
    """菜品组合关联度"""

    def test_high_affinity(self):
        # 10 / (15 + 12 - 10) = 10/17 ≈ 0.5882
        affinity = compute_combo_affinity(10, 15, 12)
        assert 0.58 < affinity < 0.60

    def test_zero_co_occurrence(self):
        assert compute_combo_affinity(0, 10, 10) == 0.0

    def test_perfect_overlap(self):
        assert compute_combo_affinity(10, 10, 10) == 1.0


class TestEstimateMarginImpact:
    """毛利优化¥影响"""

    def test_improvement(self):
        result = estimate_margin_impact(0.5, 0.6, 100, 80.0)
        # current: 100 × 80 × 0.5 = 4000
        # target: 100 × 80 × 0.6 = 4800
        assert result["monthly_delta_yuan"] == 800.0
        assert result["annual_delta_yuan"] == 9600.0

    def test_no_change(self):
        result = estimate_margin_impact(0.5, 0.5, 100, 80.0)
        assert result["monthly_delta_yuan"] == 0.0


class TestMenuAgentService:

    @pytest.fixture
    def service(self):
        return MenuAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_dashboard_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_menu_dashboard(mock_db, "S001")
        assert result["total_dishes"] == 0
        assert result["top_dishes"] == []

    @pytest.mark.asyncio
    async def test_combo_recommendations_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_combo_recommendations(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# 增收月报 (RevenueGrowth)
# ══════════════════════════════════════════════════════════════════

from src.services.revenue_growth_service import (
    compute_revenue_growth,
    compute_agent_contribution,
    RevenueGrowthService,
)


class TestComputeRevenueGrowth:
    """月环比增长"""

    def test_growth(self):
        result = compute_revenue_growth(120000, 100000)
        assert result["delta_yuan"] == 20000
        assert result["growth_rate"] == 0.2

    def test_decline(self):
        result = compute_revenue_growth(80000, 100000)
        assert result["delta_yuan"] == -20000
        assert result["growth_rate"] == -0.2

    def test_zero_previous(self):
        result = compute_revenue_growth(50000, 0)
        assert result["growth_rate"] == 1.0

    def test_both_zero(self):
        result = compute_revenue_growth(0, 0)
        assert result["growth_rate"] == 0.0


class TestComputeAgentContribution:
    """Agent贡献占比"""

    def test_normal(self):
        result = compute_agent_contribution(5000, 3000, 2000, 100000)
        assert result["agent_total_yuan"] == 10000
        assert result["agent_contribution_rate"] == 0.1

    def test_zero_revenue(self):
        result = compute_agent_contribution(100, 200, 300, 0)
        assert result["agent_contribution_rate"] == 0.0

    def test_all_zero(self):
        result = compute_agent_contribution(0, 0, 0, 100000)
        assert result["agent_total_yuan"] == 0.0


class TestRevenueGrowthService:

    @pytest.fixture
    def service(self):
        return RevenueGrowthService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_monthly_report_empty(self, service, mock_db):
        """空库生成月报"""
        # mock order stats
        mock_order_result = AsyncMock()
        mock_order_result.one = MagicMock(return_value=(0, 0))
        mock_db.execute = AsyncMock(return_value=mock_order_result)
        mock_db.scalar = AsyncMock(return_value=0)

        result = await service.generate_monthly_report(mock_db, "S001")
        assert result["total_orders"] == 0
        assert result["revenue"]["current_yuan"] == 0.0
        assert result["agent_contribution"]["agent_total_yuan"] == 0.0
