"""
Sprint 5 单元测试 — CostAgent + KitchenAgent + StoreAgent

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
from unittest.mock import AsyncMock, MagicMock


# ══════════════════════════════════════════════════════════════════
# CostAgent
# ══════════════════════════════════════════════════════════════════

from src.services.cost_agent_service import (
    compute_food_cost_rate,
    classify_cost_health,
    compute_waste_rate,
    estimate_cost_saving,
    CostAgentService,
)


class TestComputeFoodCostRate:

    def test_normal(self):
        assert compute_food_cost_rate(32000, 100000) == 0.32

    def test_zero_revenue(self):
        assert compute_food_cost_rate(1000, 0) == 0.0

    def test_low_cost(self):
        rate = compute_food_cost_rate(25000, 100000)
        assert rate == 0.25


class TestClassifyCostHealth:

    def test_excellent(self):
        assert classify_cost_health(0.28) == "excellent"

    def test_good(self):
        assert classify_cost_health(0.32) == "good"

    def test_warning(self):
        assert classify_cost_health(0.37) == "warning"

    def test_critical(self):
        assert classify_cost_health(0.42) == "critical"

    def test_boundary_30(self):
        assert classify_cost_health(0.30) == "good"

    def test_boundary_35(self):
        assert classify_cost_health(0.35) == "warning"


class TestComputeWasteRate:

    def test_normal(self):
        assert compute_waste_rate(1500, 50000) == 0.03

    def test_zero(self):
        assert compute_waste_rate(0, 50000) == 0.0

    def test_zero_usage(self):
        assert compute_waste_rate(100, 0) == 0.0


class TestEstimateCostSaving:

    def test_has_gap(self):
        result = estimate_cost_saving(0.36, 0.32, 300000)
        # gap = 4%, monthly = 0.04 × 300000 = 12000
        assert result["monthly_saving_yuan"] == 12000.0
        assert result["annual_saving_yuan"] == 144000.0

    def test_no_gap(self):
        result = estimate_cost_saving(0.30, 0.32, 300000)
        assert result["monthly_saving_yuan"] == 0.0

    def test_exact_target(self):
        result = estimate_cost_saving(0.32, 0.32, 300000)
        assert result["monthly_saving_yuan"] == 0.0


class TestCostAgentService:

    @pytest.fixture
    def service(self):
        return CostAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_waste_analysis_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_waste_analysis(mock_db, "S001")
        assert result["total_events"] == 0
        assert result["breakdown"] == []

    @pytest.mark.asyncio
    async def test_cost_by_category_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_cost_by_category(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# KitchenAgent
# ══════════════════════════════════════════════════════════════════

from src.services.kitchen_agent_service import (
    compute_dish_speed_score,
    classify_kitchen_efficiency,
    compute_return_rate,
    KitchenAgentService,
)


class TestComputeDishSpeedScore:

    def test_fast(self):
        assert compute_dish_speed_score(10) == "fast"

    def test_normal(self):
        assert compute_dish_speed_score(20) == "normal"

    def test_slow(self):
        assert compute_dish_speed_score(30) == "slow"

    def test_critical(self):
        assert compute_dish_speed_score(45) == "critical"

    def test_boundary_15(self):
        assert compute_dish_speed_score(15) == "normal"

    def test_boundary_25(self):
        assert compute_dish_speed_score(25) == "slow"


class TestClassifyKitchenEfficiency:

    def test_grade_a(self):
        assert classify_kitchen_efficiency("fast", 0.01, 0.02) == "A"

    def test_grade_b(self):
        assert classify_kitchen_efficiency("normal", 0.03, 0.05) == "B"

    def test_grade_c(self):
        assert classify_kitchen_efficiency("slow", 0.06, 0.05) == "C"

    def test_grade_d_critical_speed(self):
        assert classify_kitchen_efficiency("critical", 0.01, 0.01) == "D"

    def test_grade_d_high_return(self):
        assert classify_kitchen_efficiency("fast", 0.12, 0.01) == "D"

    def test_fast_but_high_waste(self):
        # fast + low return but high waste → still A threshold: waste < 3%
        assert classify_kitchen_efficiency("fast", 0.01, 0.05) == "B"


class TestComputeReturnRate:

    def test_normal(self):
        assert compute_return_rate(5, 100) == 0.05

    def test_zero_total(self):
        assert compute_return_rate(0, 0) == 0.0

    def test_no_returns(self):
        assert compute_return_rate(0, 100) == 0.0


class TestKitchenAgentService:

    @pytest.fixture
    def service(self):
        return KitchenAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_dish_speed_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_dish_production_speed(mock_db, "S001")
        assert result == []

    @pytest.mark.asyncio
    async def test_waste_types_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_waste_by_type(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# StoreAgent
# ══════════════════════════════════════════════════════════════════

from src.services.store_agent_service import (
    compute_store_health_score,
    classify_store_status,
    _revenue_score,
    _cost_score,
    _member_score,
    StoreAgentService,
)


class TestComputeStoreHealthScore:

    def test_all_perfect(self):
        score = compute_store_health_score(100, 100, 100, 100, 100)
        assert score == 100.0

    def test_all_zero(self):
        score = compute_store_health_score(0, 0, 0, 0, 0)
        assert score == 0.0

    def test_weighted(self):
        # 营收30% + 成本25% + 会员20% + 楼面15% + 菜品10%
        # 80*0.3 + 60*0.25 + 70*0.2 + 50*0.15 + 40*0.1
        # = 24 + 15 + 14 + 7.5 + 4 = 64.5
        score = compute_store_health_score(80, 60, 70, 50, 40)
        assert score == 64.5


class TestClassifyStoreStatus:

    def test_excellent(self):
        assert classify_store_status(85) == "excellent"

    def test_good(self):
        assert classify_store_status(65) == "good"

    def test_warning(self):
        assert classify_store_status(45) == "warning"

    def test_critical(self):
        assert classify_store_status(30) == "critical"

    def test_boundary_80(self):
        assert classify_store_status(80) == "excellent"


class TestRevenueScore:

    def test_high_growth(self):
        assert _revenue_score(0.15) == 100.0

    def test_zero_growth(self):
        assert _revenue_score(0.0) == 60.0

    def test_decline(self):
        score = _revenue_score(-0.05)
        assert 30 < score < 60


class TestCostScore:

    def test_excellent(self):
        assert _cost_score(0.28) == 100.0

    def test_high_cost(self):
        score = _cost_score(0.42)
        assert score == 20.0


class TestMemberScore:

    def test_high_vip(self):
        assert _member_score(0.45) == 100.0

    def test_low_vip(self):
        score = _member_score(0.05)
        assert score == 20.0


class TestStoreAgentService:

    @pytest.fixture
    def service(self):
        return StoreAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_cross_store_ranking_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_cross_store_ranking(mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_suggestions_generation(self, service, mock_db):
        suggestions = service._generate_suggestions(
            growth_rate=-0.05,
            cost_rate=0.38,
            s1_s2_rate=0.15,
            turnover=1.2,
            margin=0.50,
        )
        assert len(suggestions) <= 3
        assert len(suggestions) > 0
        # All 5 dimensions are underperforming, should get top 3
        assert any("食材成本率" in s or "毛利" in s or "营收" in s for s in suggestions)
