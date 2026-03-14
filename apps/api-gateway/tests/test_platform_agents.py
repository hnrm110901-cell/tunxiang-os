"""
Sprint 6 单元测试 — PeopleAgent + OntologyAgent + TenantReplicator

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
# PeopleAgent
# ══════════════════════════════════════════════════════════════════

from src.services.people_agent_service import (
    compute_labor_efficiency,
    classify_staffing_health,
    compute_turnover_risk,
    compute_labor_cost_rate,
    PeopleAgentService,
)


class TestComputeLaborEfficiency:

    def test_normal(self):
        assert compute_labor_efficiency(80000, 800) == 100.0

    def test_zero_hours(self):
        assert compute_labor_efficiency(50000, 0) == 0.0

    def test_low_efficiency(self):
        result = compute_labor_efficiency(40000, 800)
        assert result == 50.0

    def test_high_efficiency(self):
        result = compute_labor_efficiency(120000, 800)
        assert result == 150.0


class TestClassifyStaffingHealth:

    def test_optimal(self):
        assert classify_staffing_health(10, 10) == "optimal"

    def test_overstaffed(self):
        assert classify_staffing_health(13, 10) == "overstaffed"

    def test_understaffed(self):
        assert classify_staffing_health(7, 10) == "understaffed"

    def test_zero_recommended(self):
        assert classify_staffing_health(5, 0) == "unknown"

    def test_boundary_high(self):
        # 12/10 = 1.2, exactly on boundary → optimal
        assert classify_staffing_health(12, 10) == "optimal"

    def test_boundary_low(self):
        # 8/10 = 0.8, exactly on boundary → optimal
        assert classify_staffing_health(8, 10) == "optimal"


class TestComputeTurnoverRisk:

    def test_new_employee(self):
        assert compute_turnover_risk(30, 10, 10) == "high"

    def test_shift_drop_high(self):
        # recent < avg * 0.5
        assert compute_turnover_risk(180, 3, 10) == "high"

    def test_shift_drop_medium(self):
        # recent < avg * 0.8 but >= avg * 0.5
        assert compute_turnover_risk(180, 6, 10) == "medium"

    def test_normal(self):
        assert compute_turnover_risk(180, 10, 10) == "low"

    def test_zero_avg(self):
        assert compute_turnover_risk(180, 0, 0) == "low"


class TestComputeLaborCostRate:

    def test_normal(self):
        assert compute_labor_cost_rate(25000, 100000) == 0.25

    def test_zero_revenue(self):
        assert compute_labor_cost_rate(20000, 0) == 0.0

    def test_high_cost(self):
        assert compute_labor_cost_rate(35000, 100000) == 0.35


class TestPeopleAgentService:

    @pytest.fixture
    def service(self):
        return PeopleAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_employee_performance_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_employee_performance(mock_db, "S001")
        assert result == []

    @pytest.mark.asyncio
    async def test_staffing_gaps_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_staffing_gaps(mock_db, "S001", days=3)
        assert len(result) == 3
        # 没有排班和订单，所有日期都是 understaffed（0 staff vs recommended 1）
        for gap in result:
            assert gap["actual_staff"] == 0


# ══════════════════════════════════════════════════════════════════
# OntologyAgent
# ══════════════════════════════════════════════════════════════════

from src.services.ontology_agent_service import (
    compute_knowledge_coverage,
    classify_data_quality,
    compute_relationship_density,
    compute_ontology_health_score,
    OntologyAgentService,
)


class TestComputeKnowledgeCoverage:

    def test_full_coverage(self):
        assert compute_knowledge_coverage(100, 100) == 1.0

    def test_partial(self):
        assert compute_knowledge_coverage(100, 75) == 0.75

    def test_zero_total(self):
        assert compute_knowledge_coverage(0, 0) == 0.0

    def test_none_complete(self):
        assert compute_knowledge_coverage(50, 0) == 0.0


class TestClassifyDataQuality:

    def test_excellent(self):
        assert classify_data_quality(0.95) == "excellent"

    def test_good(self):
        assert classify_data_quality(0.80) == "good"

    def test_warning(self):
        assert classify_data_quality(0.55) == "warning"

    def test_critical(self):
        assert classify_data_quality(0.30) == "critical"

    def test_boundary_90(self):
        assert classify_data_quality(0.90) == "excellent"

    def test_boundary_70(self):
        assert classify_data_quality(0.70) == "good"


class TestComputeRelationshipDensity:

    def test_normal(self):
        assert compute_relationship_density(200, 100) == 2.0

    def test_zero_entities(self):
        assert compute_relationship_density(50, 0) == 0.0

    def test_sparse(self):
        assert compute_relationship_density(50, 100) == 0.5


class TestComputeOntologyHealthScore:

    def test_all_perfect(self):
        score = compute_ontology_health_score(1.0, 1.0, 1.0)
        assert score == 100.0

    def test_all_zero(self):
        score = compute_ontology_health_score(0.0, 0.0, 0.0)
        assert score == 0.0

    def test_weighted(self):
        # dish 0.8 * 40% + bom 0.6 * 35% + inv 0.5 * 25%
        # = 32 + 21 + 12.5 = 65.5
        score = compute_ontology_health_score(0.8, 0.6, 0.5)
        assert score == 65.5

    def test_cap_at_100(self):
        score = compute_ontology_health_score(1.5, 1.5, 1.5)
        assert score == 100.0


class TestOntologyAgentService:

    @pytest.fixture
    def service(self):
        return OntologyAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_dashboard_empty(self, service, mock_db):
        result = await service.get_ontology_dashboard(mock_db, "S001")
        assert result["health_score"] == 0.0
        assert result["data_quality"] == "critical"
        assert result["entity_counts"]["dishes"] == 0

    @pytest.mark.asyncio
    async def test_entity_stats_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.scalar = AsyncMock(return_value=0)

        result = await service.get_entity_stats(mock_db, "S001")
        assert result["dish_by_category"] == {}
        assert result["orphan_dishes_no_bom"] == 0

    @pytest.mark.asyncio
    async def test_data_issues_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_data_issues(mock_db, "S001")
        assert result == []


# ══════════════════════════════════════════════════════════════════
# TenantReplicator
# ══════════════════════════════════════════════════════════════════

from src.services.tenant_replicator_service import (
    compute_onboarding_progress,
    estimate_onboarding_days,
    classify_onboarding_status,
    TenantReplicatorService,
)


class TestComputeOnboardingProgress:

    def test_all_complete(self):
        result = compute_onboarding_progress(20, 10, 30, 5)
        assert result["overall_progress"] == 1.0

    def test_all_zero(self):
        result = compute_onboarding_progress(0, 0, 0, 0)
        assert result["overall_progress"] == 0.0

    def test_partial(self):
        result = compute_onboarding_progress(10, 5, 15, 3)
        # dish: 10/20=0.5, bom: 5/10=0.5, inv: 15/30=0.5, emp: 3/5=0.6
        # overall: 0.5*0.3 + 0.5*0.25 + 0.5*0.25 + 0.6*0.2 = 0.15+0.125+0.125+0.12 = 0.52
        assert result["overall_progress"] == 0.52

    def test_over_baseline(self):
        # 超过基准线也只算100%
        result = compute_onboarding_progress(50, 20, 60, 10)
        assert result["dish_progress"] == 1.0
        assert result["overall_progress"] == 1.0


class TestEstimateOnboardingDays:

    def test_complete(self):
        assert estimate_onboarding_days(1.0) == 0

    def test_half(self):
        days = estimate_onboarding_days(0.5)
        assert days == 4  # round(0.5 * 7) = 4

    def test_just_started(self):
        days = estimate_onboarding_days(0.1)
        assert days == 6  # round(0.9 * 7) = 6

    def test_zero(self):
        assert estimate_onboarding_days(0.0) == 7


class TestClassifyOnboardingStatus:

    def test_completed(self):
        assert classify_onboarding_status(1.0) == "completed"

    def test_almost_ready(self):
        assert classify_onboarding_status(0.85) == "almost_ready"

    def test_in_progress(self):
        assert classify_onboarding_status(0.55) == "in_progress"

    def test_just_started(self):
        assert classify_onboarding_status(0.20) == "just_started"

    def test_boundary_80(self):
        assert classify_onboarding_status(0.80) == "almost_ready"

    def test_boundary_40(self):
        assert classify_onboarding_status(0.40) == "in_progress"


class TestTenantReplicatorService:

    @pytest.fixture
    def service(self):
        return TenantReplicatorService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_onboarding_status_empty(self, service, mock_db):
        result = await service.get_onboarding_status(mock_db, "S001")
        assert result["status"] == "just_started"
        assert result["progress"]["overall_progress"] == 0.0
        assert result["estimated_remaining_days"] == 7

    @pytest.mark.asyncio
    async def test_multi_store_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_multi_store_onboarding(mock_db)
        assert result == []
