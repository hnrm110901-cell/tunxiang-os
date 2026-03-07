"""tests/test_financial_forecast_service.py — Phase 5 Month 7

覆盖：
  - _prev_periods
  - linear_trend
  - weighted_moving_avg
  - compute_forecast_accuracy
  - confidence_interval
  - trend_direction
  - _make_forecast_result
  - compute_revenue_forecast (mock DB)
  - compute_food_cost_rate_forecast (mock DB)
  - compute_profit_margin_forecast (mock DB)
  - compute_health_score_forecast (mock DB)
  - compute_all_forecasts (mock DB)
  - get_forecast (mock DB)
  - get_forecast_accuracy_history (mock DB)
  - backfill_actual_values (mock DB)
  - get_brand_forecast_summary (mock DB)
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.services.financial_forecast_service import (
    _prev_periods,
    linear_trend,
    weighted_moving_avg,
    compute_forecast_accuracy,
    confidence_interval,
    trend_direction,
    _make_forecast_result,
    compute_revenue_forecast,
    compute_food_cost_rate_forecast,
    compute_profit_margin_forecast,
    compute_health_score_forecast,
    compute_all_forecasts,
    get_forecast,
    get_forecast_accuracy_history,
    backfill_actual_values,
    get_brand_forecast_summary,
    MIN_PERIODS,
    FORECAST_TYPES,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _seq_db(rows_list):
    """DB mock that returns rows_list[i] on i-th execute call."""
    db = AsyncMock()
    call_count = [0]

    async def _exec(stmt, params=None):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        result.fetchall.return_value = rows_list[idx] if idx < len(rows_list) else []
        result.fetchone.return_value = rows_list[idx][0] if (idx < len(rows_list) and rows_list[idx]) else None
        return result

    db.execute = _exec
    db.commit = AsyncMock()
    return db


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

class TestPrevPeriods:
    def test_three_periods(self):
        result = _prev_periods("2026-03", 3)
        assert result == ["2025-12", "2026-01", "2026-02"]

    def test_six_periods(self):
        result = _prev_periods("2026-03", 6)
        assert len(result) == 6
        assert result[-1] == "2026-02"
        assert result[0] == "2025-09"

    def test_year_wrap(self):
        result = _prev_periods("2026-01", 2)
        assert result == ["2025-11", "2025-12"]

    def test_single_period(self):
        result = _prev_periods("2026-03", 1)
        assert result == ["2026-02"]

    def test_ascending_order(self):
        result = _prev_periods("2026-06", 6)
        assert result == sorted(result)


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数
# ══════════════════════════════════════════════════════════════════════════════

class TestLinearTrend:
    def test_ascending(self):
        pred, lo, hi = linear_trend([10, 20, 30, 40])
        assert pred > 40       # 趋势向上，预测值 > 最后一点
        assert lo <= pred <= hi  # CI包含预测点（完美线性时 lo==pred==hi）

    def test_descending(self):
        pred, lo, hi = linear_trend([40, 30, 20, 10])
        assert pred < 10       # 趋势向下

    def test_flat(self):
        pred, lo, hi = linear_trend([50, 50, 50, 50])
        assert abs(pred - 50) < 1.0   # 平稳序列预测约等于均值

    def test_single_value(self):
        pred, lo, hi = linear_trend([100])
        assert pred == 100
        assert lo < pred <= hi

    def test_two_values(self):
        pred, lo, hi = linear_trend([10, 20])
        assert pred > 20
        assert lo < pred < hi

    def test_ci_width_grows_with_noise(self):
        noisy  = [10, 50, 5, 60, 2, 55]
        smooth = [10, 20, 30, 40, 50, 60]
        _, n_lo, n_hi = linear_trend(noisy)
        _, s_lo, s_hi = linear_trend(smooth)
        assert (n_hi - n_lo) > (s_hi - s_lo)   # 噪声更大，CI更宽

    def test_periods_ahead_2(self):
        p1, _, _ = linear_trend([10, 20, 30], periods_ahead=1)
        p2, _, _ = linear_trend([10, 20, 30], periods_ahead=2)
        assert p2 > p1   # 更远的未来预测更高（上升序列）

    def test_empty_returns_zeros(self):
        pred, lo, hi = linear_trend([])
        assert pred == 0.0


class TestWeightedMovingAvg:
    def test_equal_weight_mean(self):
        # WMA with n=1: 只有一个值
        assert weighted_moving_avg([42.0]) == 42.0

    def test_increasing_gives_higher_value(self):
        values = [10, 20, 30, 40, 50]
        wma = weighted_moving_avg(values)
        mean = sum(values) / len(values)
        assert wma > mean   # 最近权重高，WMA > 简单均值

    def test_decreasing_gives_lower_value(self):
        values = [50, 40, 30, 20, 10]
        wma = weighted_moving_avg(values)
        mean = sum(values) / len(values)
        assert wma < mean

    def test_empty(self):
        assert weighted_moving_avg([]) == 0.0

    def test_multi_step_ahead_ascending(self):
        p1 = weighted_moving_avg([10, 20, 30], periods_ahead=1)
        p2 = weighted_moving_avg([10, 20, 30], periods_ahead=2)
        assert p2 >= p1   # 递推预测，上升趋势下应持续增大

    def test_result_within_reasonable_range(self):
        values = [100, 110, 105, 115, 108]
        wma = weighted_moving_avg(values)
        assert 90 < wma < 130   # 在合理范围内


class TestComputeForecastAccuracy:
    def test_exact_match(self):
        assert compute_forecast_accuracy(100, 100) == 100.0

    def test_10pct_error(self):
        acc = compute_forecast_accuracy(110, 100)
        assert abs(acc - 90.0) < 0.01

    def test_50pct_error(self):
        acc = compute_forecast_accuracy(150, 100)
        assert abs(acc - 50.0) < 0.01

    def test_over_100pct_error_clamped(self):
        acc = compute_forecast_accuracy(300, 100)
        assert acc == 0.0   # clamped to 0

    def test_zero_actual_zero_predicted(self):
        assert compute_forecast_accuracy(0, 0) == 100.0

    def test_zero_actual_nonzero_predicted(self):
        assert compute_forecast_accuracy(50, 0) == 0.0

    def test_negative_actual(self):
        acc = compute_forecast_accuracy(-110, -100)
        assert abs(acc - 90.0) < 0.01


class TestConfidenceInterval:
    def test_symmetric(self):
        lo, hi = confidence_interval([100, 100, 100], 100)
        assert abs(lo - 100) < 1e-6
        assert abs(hi - 100) < 1e-6

    def test_lo_lt_hi(self):
        lo, hi = confidence_interval([10, 30, 50, 70, 90], 50)
        assert lo < hi

    def test_wider_for_volatile(self):
        narrow_lo, narrow_hi = confidence_interval([10, 11, 10, 11], 10.5)
        wide_lo,   wide_hi   = confidence_interval([1, 100, 1, 100], 50)
        assert (wide_hi - wide_lo) > (narrow_hi - narrow_lo)

    def test_single_value(self):
        lo, hi = confidence_interval([50], 50)
        assert lo < hi


class TestTrendDirection:
    def test_up(self):
        assert trend_direction([10, 20, 30, 40]) == "up"

    def test_down(self):
        assert trend_direction([40, 30, 20, 10]) == "down"

    def test_flat(self):
        assert trend_direction([50, 50, 50, 50]) == "flat"

    def test_single(self):
        assert trend_direction([50]) == "flat"


class TestMakeForecastResult:
    def test_returns_none_for_too_few_values(self):
        result = _make_forecast_result("revenue", [1000], "2026-03", ["2026-02"])
        assert result is None

    def test_returns_dict_for_sufficient_data(self):
        values = [1000, 1100, 1200, 1300, 1400, 1500]
        periods = _prev_periods("2026-03", 6)
        result = _make_forecast_result("revenue", values, "2026-03", periods)
        assert result is not None
        assert result["forecast_type"] == "revenue"
        assert result["target_period"] == "2026-03"
        assert result["lower_bound"] < result["predicted_value"] < result["upper_bound"]
        assert len(result["history"]) == 6

    def test_confidence_pct(self):
        values = [50, 55, 60, 65, 70, 75]
        periods = _prev_periods("2026-03", 6)
        result = _make_forecast_result("food_cost_rate", values, "2026-03", periods)
        assert result["confidence_pct"] == 95.0

    def test_trend_direction_present(self):
        values = [50, 55, 60, 65, 70, 75]
        periods = _prev_periods("2026-03", 6)
        result = _make_forecast_result("revenue", values, "2026-03", periods)
        assert result["trend_direction"] in ("up", "down", "flat")

    def test_label_included(self):
        values = [50, 55, 60, 65, 70, 75]
        periods = _prev_periods("2026-03", 6)
        result = _make_forecast_result("health_score", values, "2026-03", periods)
        assert "健康评分" in result["label"]


# ══════════════════════════════════════════════════════════════════════════════
# DB 函数
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeRevenueForecast:
    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = _seq_db([[]])  # empty profit history
        result = await compute_revenue_forecast(db, "STORE001", "2026-03")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_data_returns_forecast(self):
        profit_rows = [
            ("2025-09", 80000, 28000, 15.0),
            ("2025-10", 85000, 29000, 15.5),
            ("2025-11", 82000, 28500, 15.2),
            ("2025-12", 90000, 31000, 16.0),
            ("2026-01", 88000, 30500, 15.8),
            ("2026-02", 92000, 32000, 16.5),
        ]
        # profit_history fetch + upsert
        db = _seq_db([profit_rows])
        result = await compute_revenue_forecast(db, "STORE001", "2026-03")
        assert result is not None
        assert result["forecast_type"] == "revenue"
        assert result["predicted_value"] > 0


class TestComputeFoodCostRateForecast:
    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = _seq_db([[]])
        result = await compute_food_cost_rate_forecast(db, "STORE001", "2026-03")
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_computed_correctly(self):
        # food_cost/revenue = 35000/100000 = 35%
        profit_rows = [
            ("2025-09", 100000, 35000, 12.0),
            ("2025-10", 100000, 35000, 12.0),
            ("2025-11", 100000, 35000, 12.0),
            ("2025-12", 100000, 35000, 12.0),
        ]
        db = _seq_db([profit_rows])
        result = await compute_food_cost_rate_forecast(db, "STORE001", "2026-03")
        assert result is not None
        # Flat series → predicted ≈ 35%
        assert abs(result["predicted_value"] - 35.0) < 1.0


class TestComputeProfitMarginForecast:
    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = _seq_db([[]])
        result = await compute_profit_margin_forecast(db, "STORE001", "2026-03")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_data(self):
        profit_rows = [
            ("2025-09", 100000, 35000, 15.0),
            ("2025-10", 110000, 37000, 15.5),
            ("2025-11", 105000, 36000, 15.2),
        ]
        db = _seq_db([profit_rows])
        result = await compute_profit_margin_forecast(db, "STORE001", "2026-03")
        assert result is not None
        assert result["forecast_type"] == "profit_margin"


class TestComputeHealthScoreForecast:
    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = _seq_db([[]])
        result = await compute_health_score_forecast(db, "STORE001", "2026-03")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_improving_scores(self):
        health_rows = [
            ("2025-09", 60.0), ("2025-10", 63.0), ("2025-11", 65.0),
            ("2025-12", 68.0), ("2026-01", 70.0), ("2026-02", 72.0),
        ]
        db = _seq_db([health_rows])
        result = await compute_health_score_forecast(db, "STORE001", "2026-03")
        assert result is not None
        assert result["predicted_value"] > 60.0
        assert result["trend_direction"] == "up"


class TestComputeAllForecasts:
    @pytest.mark.asyncio
    async def test_returns_all_four_keys(self):
        profit_rows = [
            ("2025-09", 80000, 28000, 15.0),
            ("2025-10", 85000, 29000, 15.5),
            ("2025-11", 82000, 28500, 15.2),
        ]
        health_rows = [("2025-09", 70.0), ("2025-10", 72.0), ("2025-11", 74.0)]
        # compute_all calls 4 sub-functions each needing 1 DB read
        # revenue: profit_rows
        # food_cost_rate: profit_rows (same table, second call)
        # profit_margin: profit_rows (third call)
        # health_score: health_rows (fourth call)
        db = _seq_db([profit_rows, profit_rows, profit_rows, health_rows])
        result = await compute_all_forecasts(db, "STORE001", "2026-03")
        assert result["store_id"] == "STORE001"
        assert result["target_period"] == "2026-03"
        for key in FORECAST_TYPES:
            assert key in result

    @pytest.mark.asyncio
    async def test_partial_failure_graceful(self):
        """If all DB queries return empty, all forecast types should be None, not crash."""
        db = _seq_db([[], [], [], []])
        result = await compute_all_forecasts(db, "STORE001", "2026-03")
        for key in FORECAST_TYPES:
            assert result[key] is None


class TestGetForecast:
    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = _seq_db([[]])
        result = await get_forecast(db, "STORE001", "2026-03")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_forecast_list(self):
        rows = [
            ("revenue",        88000, 80000, 96000, 95.0, "weighted_moving_avg", 6, None, None, None),
            ("food_cost_rate",    32,    28,    36, 95.0, "weighted_moving_avg", 6, None, None, None),
        ]
        db = _seq_db([rows])
        result = await get_forecast(db, "STORE001", "2026-03")
        assert result is not None
        assert result["store_id"] == "STORE001"
        assert len(result["forecasts"]) == 2
        assert result["forecasts"][0]["forecast_type"] == "revenue"
        assert result["forecasts"][0]["label"] == "月净收入 (¥)"


class TestGetForecastAccuracyHistory:
    @pytest.mark.asyncio
    async def test_empty(self):
        db = _seq_db([[]])
        result = await get_forecast_accuracy_history(db, "STORE001")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_records(self):
        rows = [
            ("revenue", "2026-01", 85000, 87000, 97.7),
            ("revenue", "2026-02", 88000, 86000, 97.7),
        ]
        db = _seq_db([rows])
        result = await get_forecast_accuracy_history(db, "STORE001")
        assert len(result) == 2
        assert result[0]["forecast_type"] == "revenue"
        assert result[0]["accuracy_pct"] == 97.7


class TestBackfillActualValues:
    @pytest.mark.asyncio
    async def test_no_data_returns_zero_updated(self):
        # profit_row → None, health_row → None
        db = _seq_db([[], []])
        result = await backfill_actual_values(db, "STORE001", "2026-02")
        assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_updates_when_data_present(self):
        db = AsyncMock()
        call_idx = [0]

        def _mock(fetchone_val):
            m = MagicMock()
            m.fetchone.return_value = fetchone_val
            return m

        # UPDATE calls also consume execute() slots — account for all 10 calls:
        # 0: SELECT profit_attribution
        # 1: SELECT revenue pred  → updated+1
        # 2: UPDATE revenue
        # 3: SELECT food_cost_rate pred → updated+1
        # 4: UPDATE food_cost_rate
        # 5: SELECT profit_margin pred  → updated+1
        # 6: UPDATE profit_margin
        # 7: SELECT health_score
        # 8: SELECT health_score pred  → updated+1
        # 9: UPDATE health_score
        responses = [
            _mock((100000, 35000, 15.0)),  # 0: profit_attribution
            _mock((95000,)),               # 1: revenue pred
            _mock(None),                   # 2: UPDATE revenue (fetchone not called)
            _mock((36.0,)),                # 3: food_cost_rate pred
            _mock(None),                   # 4: UPDATE food_cost_rate
            _mock((14.0,)),                # 5: profit_margin pred
            _mock(None),                   # 6: UPDATE profit_margin
            _mock((72.0,)),                # 7: health_score SELECT
            _mock((70.0,)),                # 8: health_score pred
            _mock(None),                   # 9: UPDATE health_score
        ]

        async def _exec(stmt, params=None):
            idx = call_idx[0]
            call_idx[0] += 1
            return responses[idx] if idx < len(responses) else _mock(None)

        db.execute = _exec
        db.commit = AsyncMock()
        result = await backfill_actual_values(db, "STORE001", "2026-02")
        assert result["updated"] == 4   # revenue + food_cost_rate + profit_margin + health_score


class TestGetBrandForecastSummary:
    @pytest.mark.asyncio
    async def test_empty(self):
        db = _seq_db([[]])
        result = await get_brand_forecast_summary(db, "BRAND001", "2026-03")
        assert result["by_type"] == {}

    @pytest.mark.asyncio
    async def test_aggregates_multiple_stores(self):
        rows = [
            ("STORE001", "revenue", 90000),
            ("STORE002", "revenue", 80000),
            ("STORE003", "revenue", 85000),
            ("STORE001", "health_score", 75),
            ("STORE002", "health_score", 65),
        ]
        db = _seq_db([rows])
        result = await get_brand_forecast_summary(db, "BRAND001", "2026-03")
        rev = result["by_type"]["revenue"]
        assert rev["count"] == 3
        assert abs(rev["avg"] - 85000) < 1.0
        assert rev["min"] == 80000
        assert rev["max"] == 90000
        assert result["by_type"]["health_score"]["count"] == 2
