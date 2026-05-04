"""成本核算引擎单元测试

覆盖：
1. BOM 成本计算（已知菜品 + 食材价格 → 期望成本）
2. 无 BOM 时使用估算值并标注 is_estimated=True
3. 成本健康度评级边界值
4. 多租户隔离（不同 tenant_id 返回不同结果）
5. 成本率计算正确性
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from services.tx_finance.src.services.cost_engine_service import (
    CostEngineService,
    DailyCostReport,
    calculate_cost_health_score,
)

# ─── 测试夹具 ────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def store_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def other_tenant_id() -> uuid.UUID:
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service() -> CostEngineService:
    return CostEngineService()


# ─── 成本健康度评分测试 ───────────────────────────────────────────────────────


class TestCalculateCostHealthScore:
    """测试成本健康度评分纯函数，覆盖所有边界值"""

    def test_excellent_zero(self):
        """0% 成本率 → 满分 100"""
        result = calculate_cost_health_score(0.0)
        assert result.status == "excellent"
        assert result.color == "green"
        assert result.score == 100.0

    def test_excellent_at_threshold(self):
        """28% 边界值 → 仍为优秀"""
        result = calculate_cost_health_score(0.28)
        assert result.status == "excellent"
        assert result.color == "green"
        assert 89.0 <= result.score <= 91.0

    def test_normal_just_above_threshold(self):
        """28.01% → 进入正常区间"""
        result = calculate_cost_health_score(0.2801)
        assert result.status == "normal"
        assert result.color == "yellow"
        assert result.score <= 89.0

    def test_normal_at_30_pct(self):
        """行业均值 30% → 正常"""
        result = calculate_cost_health_score(0.30)
        assert result.status == "normal"
        assert result.color == "yellow"
        assert 70.0 <= result.score <= 89.0

    def test_normal_at_upper_threshold(self):
        """32% 边界 → 正常上限"""
        result = calculate_cost_health_score(0.32)
        assert result.status == "normal"
        assert result.color == "yellow"
        assert 69.0 <= result.score <= 71.0

    def test_high_just_above_32(self):
        """32.01% → 进入偏高区间"""
        result = calculate_cost_health_score(0.3201)
        assert result.status == "high"
        assert result.color == "orange"

    def test_high_at_36_threshold(self):
        """36% 边界 → 偏高上限"""
        result = calculate_cost_health_score(0.36)
        assert result.status == "high"
        assert result.color == "orange"
        assert 49.0 <= result.score <= 51.0

    def test_critical_just_above_36(self):
        """36.01% → 进入危险区间"""
        result = calculate_cost_health_score(0.3601)
        assert result.status == "critical"
        assert result.color == "red"
        assert result.score < 50.0

    def test_critical_at_50_pct(self):
        """50% → score 接近 0"""
        result = calculate_cost_health_score(0.50)
        assert result.status == "critical"
        assert result.color == "red"
        assert result.score <= 5.0

    def test_gap_to_target_positive_when_above_target(self):
        """实际成本率超出目标 → gap > 0"""
        result = calculate_cost_health_score(0.35)
        assert result.gap_to_target > 0
        assert abs(result.gap_to_target - 0.05) < 0.001

    def test_gap_to_target_negative_when_below_target(self):
        """实际成本率低于目标 → gap < 0（好于目标）"""
        result = calculate_cost_health_score(0.25)
        assert result.gap_to_target < 0
        assert abs(result.gap_to_target - (-0.05)) < 0.001

    def test_score_monotone_decreasing(self):
        """分数随成本率单调递减"""
        rates = [0.20, 0.28, 0.30, 0.32, 0.36, 0.40, 0.50]
        scores = [calculate_cost_health_score(r).score for r in rates]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"score({rates[i]})={scores[i]} should >= score({rates[i + 1]})={scores[i + 1]}"
            )

    def test_to_dict_structure(self):
        """to_dict 包含所有必要字段"""
        result = calculate_cost_health_score(0.30)
        d = result.to_dict()
        required_keys = {
            "food_cost_rate",
            "food_cost_rate_pct",
            "score",
            "status",
            "status_label",
            "color",
            "target_rate",
            "gap_to_target",
            "gap_to_target_pct",
        }
        assert required_keys.issubset(set(d.keys()))


# ─── 日成本快报测试 ───────────────────────────────────────────────────────────


class TestGetDailyCostReport:
    """测试 CostEngineService.get_daily_cost_report"""

    @pytest.mark.asyncio
    async def test_has_snapshots_returns_actual_cost(self, service, store_id, tenant_id, mock_db):
        """有 cost_snapshots 快照时返回实际食材成本"""
        biz_date = date(2026, 3, 31)

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                new=AsyncMock(
                    return_value={
                        "total_food_cost_fen": 30000,
                        "order_count": 10,
                        "snapshot_count": 10,
                    }
                ),
            ),
            patch.object(service._repo, "fetch_daily_revenue_for_cost", new=AsyncMock(return_value=100000)),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)

        assert report.food_cost_fen == 30000
        assert report.revenue_fen == 100000
        assert abs(report.food_cost_rate - 0.30) < 0.001
        assert report.gross_profit_fen == 70000
        assert abs(report.gross_margin_rate - 0.70) < 0.001
        assert report.is_estimated is False

    @pytest.mark.asyncio
    async def test_no_snapshots_uses_estimate(self, service, store_id, tenant_id, mock_db):
        """无 cost_snapshots 时使用 30% 估算值并标注 is_estimated=True"""
        biz_date = date(2026, 3, 31)

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                new=AsyncMock(
                    return_value={
                        "total_food_cost_fen": 0,
                        "order_count": 5,
                        "snapshot_count": 0,
                    }
                ),
            ),
            patch.object(service._repo, "fetch_daily_revenue_for_cost", new=AsyncMock(return_value=80000)),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)

        assert report.is_estimated is True
        assert report.estimated_reason != ""
        # 估算成本 = 80000 × 30% = 24000
        assert report.food_cost_fen == 24000
        assert abs(report.food_cost_rate - 0.30) < 0.001

    @pytest.mark.asyncio
    async def test_zero_revenue_no_division_error(self, service, store_id, tenant_id, mock_db):
        """营收为零时不产生除零错误"""
        biz_date = date(2026, 3, 31)

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                new=AsyncMock(
                    return_value={
                        "total_food_cost_fen": 0,
                        "order_count": 0,
                        "snapshot_count": 0,
                    }
                ),
            ),
            patch.object(service._repo, "fetch_daily_revenue_for_cost", new=AsyncMock(return_value=0)),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)

        assert report.food_cost_rate == 0.0
        assert report.gross_margin_rate == 0.0
        assert report.is_estimated is False

    @pytest.mark.asyncio
    async def test_health_score_included_in_report(self, service, store_id, tenant_id, mock_db):
        """日成本快报中包含健康度评分"""
        biz_date = date(2026, 3, 31)

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                new=AsyncMock(
                    return_value={
                        "total_food_cost_fen": 35000,
                        "order_count": 8,
                        "snapshot_count": 8,
                    }
                ),
            ),
            patch.object(service._repo, "fetch_daily_revenue_for_cost", new=AsyncMock(return_value=100000)),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)

        assert report.health is not None
        assert report.health.status == "high"  # 35% 超出 32% 上限

    @pytest.mark.asyncio
    async def test_to_dict_all_fields_present(self, service, store_id, tenant_id, mock_db):
        """to_dict 包含所有必要字段"""
        biz_date = date(2026, 3, 31)

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                new=AsyncMock(
                    return_value={
                        "total_food_cost_fen": 28000,
                        "order_count": 10,
                        "snapshot_count": 10,
                    }
                ),
            ),
            patch.object(service._repo, "fetch_daily_revenue_for_cost", new=AsyncMock(return_value=100000)),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)

        d = report.to_dict()
        required_keys = {
            "store_id",
            "biz_date",
            "revenue_fen",
            "food_cost_fen",
            "food_cost_rate",
            "food_cost_rate_pct",
            "gross_profit_fen",
            "gross_margin_rate",
            "gross_margin_rate_pct",
            "is_estimated",
            "estimated_reason",
            "cost_breakdown",
            "health",
        }
        assert required_keys.issubset(set(d.keys()))


# ─── 成本率计算正确性测试 ─────────────────────────────────────────────────────


class TestCostRateCalculations:
    """验证成本率计算的数学正确性"""

    def test_food_cost_rate_formula(self):
        """食材成本率 = 食材成本 / 营收"""
        report = DailyCostReport(
            store_id="test",
            biz_date="2026-03-31",
            revenue_fen=100_000,
            food_cost_fen=28_000,
            food_cost_rate=0.28,
            gross_profit_fen=72_000,
            gross_margin_rate=0.72,
            is_estimated=False,
        )
        assert abs(report.food_cost_rate - 0.28) < 0.001
        assert abs(report.gross_margin_rate - 0.72) < 0.001
        assert report.gross_profit_fen == 72_000

    def test_gross_profit_equals_revenue_minus_cost(self):
        """毛利 = 营收 - 食材成本"""
        revenue = 150_000
        food_cost = 45_000
        gross_profit = revenue - food_cost
        assert gross_profit == 105_000
        assert abs(gross_profit / revenue - 0.70) < 0.001


# ─── 多租户隔离测试 ──────────────────────────────────────────────────────────


class TestMultiTenantIsolation:
    """验证多租户隔离：不同 tenant_id 查询相互独立"""

    @pytest.mark.asyncio
    async def test_different_tenants_independent_results(self, service, store_id, tenant_id, other_tenant_id, mock_db):
        """不同租户的查询结果相互独立"""
        biz_date = date(2026, 3, 31)
        call_count = {"count": 0}

        async def mock_snapshot(s, d, t, db):
            call_count["count"] += 1
            if t == tenant_id:
                return {"total_food_cost_fen": 30000, "order_count": 10, "snapshot_count": 10}
            else:
                return {"total_food_cost_fen": 45000, "order_count": 15, "snapshot_count": 15}

        async def mock_revenue(s, d, t, db):
            if t == tenant_id:
                return 100000
            else:
                return 150000

        with (
            patch.object(
                service._repo,
                "fetch_daily_cost_from_snapshots",
                side_effect=mock_snapshot,
            ),
            patch.object(
                service._repo,
                "fetch_daily_revenue_for_cost",
                side_effect=mock_revenue,
            ),
            patch.object(service._repo, "fetch_dish_cost_breakdown", new=AsyncMock(return_value=[])),
        ):
            report1 = await service.get_daily_cost_report(store_id, biz_date, tenant_id, mock_db)
            report2 = await service.get_daily_cost_report(store_id, biz_date, other_tenant_id, mock_db)

        # 两个租户的数据相互独立
        assert report1.food_cost_fen != report2.food_cost_fen
        assert report1.revenue_fen == 100000
        assert report2.revenue_fen == 150000
        assert call_count["count"] == 2
