"""
LaborCostService 单元测试
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.labor_cost_service import (
    LaborCostService,
    _build_rank_insight,
    _period_range,
    _row_to_snapshot_dict,
    compute_labor_cost_rate,
    compute_overtime_cost,
    compute_variance,
)


def _result_with_row(row):
    result = MagicMock()
    result.fetchone.return_value = row
    return result


class TestPureFunctions:
    def test_compute_labor_cost_rate_zero_revenue(self):
        assert compute_labor_cost_rate(1000, 0) == 0.0

    def test_compute_labor_cost_rate_normal(self):
        assert compute_labor_cost_rate(2500, 10000) == 25.0

    def test_compute_variance_saving(self):
        result = compute_variance(actual_rate=20, budget_rate=25, revenue_yuan=10000)
        assert result["status"] == "saving"
        assert result["saving_yuan"] == 500.0
        assert result["overspend_yuan"] == 0.0

    def test_compute_variance_warning(self):
        result = compute_variance(actual_rate=28, budget_rate=25, revenue_yuan=10000)
        assert result["status"] == "warning"
        assert result["overspend_yuan"] == 300.0

    def test_compute_variance_critical(self):
        result = compute_variance(actual_rate=32, budget_rate=25, revenue_yuan=10000)
        assert result["status"] == "critical"

    def test_compute_overtime_cost_default_multiplier(self):
        assert compute_overtime_cost(2.0) == 60.0

    def test_period_range_weekly(self):
        # 2026-03-11 周三 -> 起始应为周一 2026-03-09
        start, end = _period_range(date(2026, 3, 11), "weekly")
        assert str(start) == "2026-03-09"
        assert str(end) == "2026-03-11"

    def test_row_to_snapshot_dict(self):
        row = MagicMock()
        row.snapshot_date = date(2026, 3, 9)
        row.actual_revenue_yuan = 10000
        row.actual_labor_cost_yuan = 2500
        row.actual_labor_cost_rate = 25
        row.budgeted_labor_cost_yuan = 2600
        row.budgeted_labor_cost_rate = 26
        row.variance_yuan = -100
        row.variance_pct = -1
        row.headcount_actual = 10
        row.headcount_scheduled = 11
        row.overtime_hours = 2
        row.overtime_cost_yuan = 60
        d = _row_to_snapshot_dict(row)
        assert d["actual_labor_cost_rate"] == 25.0
        assert d["headcount_actual"] == 10
        assert d["overtime_cost_yuan"] == 60.0

    def test_build_rank_insight_best_rank(self):
        text = _build_rank_insight("S001", rank=1, total=5, rate=20.0, avg=24.0)
        assert "最优" in text


class TestServicePaths:
    @pytest.mark.asyncio
    async def test_compute_and_save_snapshot_with_given_actual_cost(self):
        db = AsyncMock()
        with (
            patch.object(LaborCostService, "_fetch_daily_revenue", new_callable=AsyncMock, return_value=10000.0),
            patch.object(LaborCostService, "_fetch_shift_stats", new_callable=AsyncMock, return_value={"headcount_actual": 10, "headcount_scheduled": 11, "overtime_hours": 2.0}),
            patch.object(LaborCostService, "_fetch_budget", new_callable=AsyncMock, return_value={"target_labor_cost_rate": 26.0, "daily_budget_yuan": None}),
            patch.object(LaborCostService, "_estimate_labor_cost", new_callable=AsyncMock) as mock_estimate,
            patch.object(LaborCostService, "_upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
        ):
            snapshot = await LaborCostService.compute_and_save_snapshot(
                store_id="S001",
                snapshot_date=date(2026, 3, 9),
                db=db,
                actual_labor_cost_yuan=2500.0,
            )
        mock_estimate.assert_not_awaited()
        mock_upsert.assert_awaited_once()
        assert snapshot["actual_labor_cost_rate"] == 25.0
        assert snapshot["status"] in {"saving", "ok", "warning", "critical"}

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found_returns_none(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_with_row(None))
        result = await LaborCostService.get_snapshot("S001", date(2026, 3, 9), db)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_found(self):
        db = AsyncMock()
        row = MagicMock()
        row.snapshot_date = date(2026, 3, 9)
        row.actual_revenue_yuan = 10000
        row.actual_labor_cost_yuan = 2600
        row.actual_labor_cost_rate = 26
        row.budgeted_labor_cost_yuan = 2500
        row.budgeted_labor_cost_rate = 25
        row.variance_yuan = 100
        row.variance_pct = 1
        row.headcount_actual = 10
        row.headcount_scheduled = 10
        row.overtime_hours = 1.5
        row.overtime_cost_yuan = 45
        db.execute = AsyncMock(return_value=_result_with_row(row))
        result = await LaborCostService.get_snapshot("S001", date(2026, 3, 9), db)
        assert result is not None
        assert result["actual_labor_cost_rate"] == 26.0

    @pytest.mark.asyncio
    async def test_get_cost_trend_no_data(self):
        db = AsyncMock()
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=empty_result)
        result = await LaborCostService.get_cost_trend("S001", date(2026, 3, 1), date(2026, 3, 9), db)
        assert result["period_status"] == "no_data"
        assert result["days"] == []

    @pytest.mark.asyncio
    async def test_refresh_store_rankings_no_rows(self):
        db = AsyncMock()
        rows_result = MagicMock()
        rows_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=rows_result)
        result = await LaborCostService.refresh_store_rankings("B001", date(2026, 3, 9), "daily", db)
        assert result["total_stores"] == 0
        assert result["rankings"] == []

    @pytest.mark.asyncio
    async def test_upsert_snapshot_rollback_on_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db error"))
        db.rollback = AsyncMock()
        with pytest.raises(RuntimeError, match="db error"):
            await LaborCostService._upsert_snapshot(
                {
                    "store_id": "S001",
                    "snapshot_date": "2026-03-09",
                    "actual_revenue_yuan": 10000,
                    "actual_labor_cost_yuan": 2500,
                    "actual_labor_cost_rate": 25.0,
                    "budgeted_labor_cost_yuan": 2600,
                    "budgeted_labor_cost_rate": 26.0,
                    "variance_yuan": -100,
                    "variance_pct": -1,
                    "headcount_actual": 10,
                    "headcount_scheduled": 11,
                    "overtime_hours": 2,
                    "overtime_cost_yuan": 60,
                },
                db,
            )
        db.rollback.assert_awaited_once()

