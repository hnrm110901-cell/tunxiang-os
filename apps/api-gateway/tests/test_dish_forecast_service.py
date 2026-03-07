"""Tests for dish_forecast_service — Phase 6 Month 7"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import sys, types

cfg_mod = types.ModuleType("src.core.config")
cfg_mod.settings = MagicMock(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    redis_url="redis://localhost",
    secret_key="test",
)
sys.modules.setdefault("src.core.config", cfg_mod)
sys.modules.setdefault("src.core.database", types.ModuleType("src.core.database"))

from src.services.dish_forecast_service import (
    compute_weighted_avg,
    compute_trend_factor,
    apply_lifecycle_adjustment,
    compute_confidence_interval,
    build_forecast_record,
    _next_period,
    _start_period,
    generate_dish_forecasts,
    get_dish_forecasts,
    get_forecast_summary,
    get_forecast_accuracy,
    get_dish_forecast_history,
    LIFECYCLE_ADJUSTMENT,
)


# ── TestComputeWeightedAvg ────────────────────────────────────────────────────
class TestComputeWeightedAvg:
    def test_empty_returns_zero(self):
        assert compute_weighted_avg([]) == 0.0

    def test_single_value(self):
        assert compute_weighted_avg([100.0]) == pytest.approx(100.0)

    def test_default_weights_recency_bias(self):
        # weights [1,2,3] → (100*1+200*2+300*3)/6 = 1400/6 ≈ 233.3
        result = compute_weighted_avg([100.0, 200.0, 300.0])
        assert result == pytest.approx(1400 / 6, abs=0.1)

    def test_custom_equal_weights_is_mean(self):
        result = compute_weighted_avg([100.0, 200.0, 300.0], [1, 1, 1])
        assert result == pytest.approx(200.0, abs=0.1)

    def test_mismatched_weights_falls_back_to_default(self):
        # weights length mismatch → default weights used
        result = compute_weighted_avg([100.0, 200.0], [1])
        # default [1,2] → (100+400)/3 ≈ 166.7
        assert result == pytest.approx(500 / 3, abs=0.1)

    def test_zero_weight_total_returns_zero(self):
        assert compute_weighted_avg([100.0], [0]) == 0.0


# ── TestComputeTrendFactor ────────────────────────────────────────────────────
class TestComputeTrendFactor:
    def test_single_value_returns_zero(self):
        assert compute_trend_factor([100.0]) == 0.0

    def test_empty_returns_zero(self):
        assert compute_trend_factor([]) == 0.0

    def test_flat_series_returns_zero(self):
        assert compute_trend_factor([100.0, 100.0, 100.0]) == 0.0

    def test_upward_trend_positive(self):
        trend = compute_trend_factor([100.0, 110.0, 120.0, 130.0])
        assert trend > 0

    def test_downward_trend_negative(self):
        trend = compute_trend_factor([130.0, 120.0, 110.0, 100.0])
        assert trend < 0

    def test_zero_mean_returns_zero(self):
        assert compute_trend_factor([0.0, 0.0, 0.0]) == 0.0

    def test_steep_upward_larger_than_mild(self):
        steep = compute_trend_factor([100.0, 200.0, 300.0])
        mild  = compute_trend_factor([100.0, 105.0, 110.0])
        assert abs(steep) > abs(mild)


# ── TestApplyLifecycleAdjustment ──────────────────────────────────────────────
class TestApplyLifecycleAdjustment:
    def test_launch_increases(self):
        result = apply_lifecycle_adjustment(100.0, 'launch')
        assert result == pytest.approx(115.0, abs=0.1)

    def test_growth_increases(self):
        result = apply_lifecycle_adjustment(100.0, 'growth')
        assert result == pytest.approx(110.0, abs=0.1)

    def test_peak_no_change(self):
        assert apply_lifecycle_adjustment(100.0, 'peak') == pytest.approx(100.0)

    def test_decline_decreases(self):
        result = apply_lifecycle_adjustment(100.0, 'decline')
        assert result == pytest.approx(92.0, abs=0.1)

    def test_exit_large_decrease(self):
        result = apply_lifecycle_adjustment(100.0, 'exit')
        assert result == pytest.approx(80.0, abs=0.1)

    def test_unknown_phase_no_change(self):
        assert apply_lifecycle_adjustment(100.0, 'unknown') == pytest.approx(100.0)


# ── TestComputeConfidenceInterval ─────────────────────────────────────────────
class TestComputeConfidenceInterval:
    def test_single_period_wide(self):
        low, high = compute_confidence_interval(100.0, 1)
        uncertainty = 0.30 - 1 * 0.04   # = 0.26
        assert low  == pytest.approx(74.0, abs=1.0)
        assert high == pytest.approx(126.0, abs=1.0)

    def test_six_periods_narrow(self):
        low, high = compute_confidence_interval(100.0, 6)
        # uncertainty = max(0.10, 0.30 - 6*0.04) = max(0.10, 0.06) = 0.10
        assert low  == pytest.approx(90.0, abs=0.5)
        assert high == pytest.approx(110.0, abs=0.5)

    def test_many_periods_floor_at_10_pct(self):
        low, high = compute_confidence_interval(100.0, 20)
        assert low  == pytest.approx(90.0, abs=0.5)
        assert high == pytest.approx(110.0, abs=0.5)

    def test_low_never_negative(self):
        low, _ = compute_confidence_interval(5.0, 1)
        assert low >= 0.0

    def test_symmetric_around_point(self):
        low, high = compute_confidence_interval(100.0, 4)
        assert abs((high - 100) - (100 - low)) < 1.0


# ── TestBuildForecastRecord ───────────────────────────────────────────────────
class TestBuildForecastRecord:
    def _history(self, n=4, base_orders=100, base_revenue=3800.0, trend=0):
        """Generate n history records with optional linear trend."""
        return [
            {
                'period':              f'2024-{10+i:02d}',
                'order_count':         int(base_orders + i * trend),
                'revenue_yuan':        base_revenue + i * trend * 38,
                'food_cost_rate':      30.0,
                'gross_profit_margin': 62.0,
            }
            for i in range(n)
        ]

    def test_empty_history_returns_none(self):
        assert build_forecast_record('S001', '2025-02', '2025-01',
                                     'D001', '宫保鸡丁', '热菜', []) is None

    def test_basic_structure(self):
        rec = build_forecast_record('S001', '2025-02', '2025-01',
                                    'D001', '宫保鸡丁', '热菜',
                                    self._history(), 'peak')
        assert rec is not None
        assert rec['store_id']        == 'S001'
        assert rec['forecast_period'] == '2025-02'
        assert rec['base_period']     == '2025-01'
        assert rec['dish_id']         == 'D001'
        assert rec['lifecycle_phase'] == 'peak'

    def test_peak_no_lc_adjustment(self):
        rec = build_forecast_record('S001', '2025-02', '2025-01',
                                    'D001', '宫保鸡丁', '热菜',
                                    self._history(4, 100, 3800.0), 'peak')
        assert rec['lifecycle_adj_pct'] == pytest.approx(0.0)

    def test_growth_increases_prediction(self):
        history = self._history(4, 100, 3800.0, trend=0)
        peak_rec   = build_forecast_record('S001', '2025-02', '2025-01',
                                           'D001', 'X', None, history, 'peak')
        growth_rec = build_forecast_record('S001', '2025-02', '2025-01',
                                           'D001', 'X', None, history, 'growth')
        assert growth_rec['predicted_revenue_yuan'] > peak_rec['predicted_revenue_yuan']

    def test_decline_decreases_prediction(self):
        history = self._history(4, 100, 3800.0, trend=0)
        peak_rec    = build_forecast_record('S001', '2025-02', '2025-01',
                                            'D001', 'X', None, history, 'peak')
        decline_rec = build_forecast_record('S001', '2025-02', '2025-01',
                                            'D001', 'X', None, history, 'decline')
        assert decline_rec['predicted_revenue_yuan'] < peak_rec['predicted_revenue_yuan']

    def test_confidence_interval_bounds(self):
        rec = build_forecast_record('S001', '2025-02', '2025-01',
                                    'D001', 'X', None, self._history(4), 'peak')
        assert rec['predicted_order_low']  <= rec['predicted_order_count']
        assert rec['predicted_order_high'] >= rec['predicted_order_count']
        assert rec['predicted_revenue_low']  <= rec['predicted_revenue_yuan']
        assert rec['predicted_revenue_high'] >= rec['predicted_revenue_yuan']

    def test_single_period_history_works(self):
        history = [{'period': '2025-01', 'order_count': 120, 'revenue_yuan': 4560.0,
                    'food_cost_rate': 28.0, 'gross_profit_margin': 62.0}]
        rec = build_forecast_record('S001', '2025-02', '2025-01',
                                    'D001', '宫保鸡丁', None, history, 'peak')
        assert rec is not None
        assert rec['periods_used'] == 1

    def test_upward_trend_increases_forecast(self):
        trending   = self._history(4, 100, 3800.0, trend=5)
        flat       = self._history(4, 100, 3800.0, trend=0)
        rec_trend  = build_forecast_record('S001', '2025-02', '2025-01',
                                           'D001', 'X', None, trending, 'peak')
        rec_flat   = build_forecast_record('S001', '2025-02', '2025-01',
                                           'D001', 'X', None, flat,    'peak')
        assert rec_trend['predicted_order_count'] > rec_flat['predicted_order_count']

    def test_predicted_revenue_nonnegative(self):
        # Even exit phase shouldn't go negative
        history = self._history(2, 10, 200.0)
        rec = build_forecast_record('S001', '2025-02', '2025-01',
                                    'D001', 'X', None, history, 'exit')
        assert rec['predicted_revenue_yuan'] >= 0.0


# ── TestNextPeriod / StartPeriod ──────────────────────────────────────────────
class TestNextPeriod:
    def test_normal(self):
        assert _next_period('2025-06') == '2025-07'

    def test_december_wraps(self):
        assert _next_period('2025-12') == '2026-01'

    def test_january(self):
        assert _next_period('2025-01') == '2025-02'


class TestStartPeriod:
    def test_no_wrap(self):
        assert _start_period('2025-06', 6) == '2025-01'

    def test_year_wrap(self):
        assert _start_period('2025-03', 6) == '2024-10'

    def test_single(self):
        assert _start_period('2025-06', 1) == '2025-06'


# ── DB helper ─────────────────────────────────────────────────────────────────
def _make_db(call_returns: list):
    db = AsyncMock()
    results = iter(call_returns)
    async def execute(sql, params=None):
        result = MagicMock()
        try:
            result.fetchall.return_value = next(results)
        except StopIteration:
            result.fetchall.return_value = []
        result.rowcount = 1
        return result
    db.execute = execute
    db.commit = AsyncMock()
    return db


def _hist_row(dish_id, dish_name, period, orders, revenue, fcr=30.0, gpm=62.0):
    return (dish_id, dish_name, '热菜', period, orders, revenue, fcr, gpm)


# ── TestGenerateDishForecasts ─────────────────────────────────────────────────
class TestGenerateDishForecasts:
    @pytest.mark.asyncio
    async def test_basic_generation(self):
        hist_rows = [
            _hist_row('D001', '宫保鸡丁', '2024-10', 100, 3800.0),
            _hist_row('D001', '宫保鸡丁', '2024-11', 110, 4180.0),
            _hist_row('D001', '宫保鸡丁', '2024-12', 120, 4560.0),
            _hist_row('D002', '麻婆豆腐', '2024-10', 200, 4800.0),
            _hist_row('D002', '麻婆豆腐', '2024-11', 205, 4920.0),
            _hist_row('D002', '麻婆豆腐', '2024-12', 210, 5040.0),
        ]
        lc_rows = [('D001', 'growth'), ('D002', 'peak')]
        db = _make_db([hist_rows, lc_rows])
        result = await generate_dish_forecasts(db, 'S001', '2024-12')
        assert result['dish_count'] == 2
        assert result['forecast_period'] == '2025-01'
        assert result['total_predicted_revenue'] > 0

    @pytest.mark.asyncio
    async def test_explicit_forecast_period(self):
        hist_rows = [_hist_row('D001', '宫保鸡丁', '2025-01', 120, 4560.0)]
        lc_rows   = []
        db = _make_db([hist_rows, lc_rows])
        result = await generate_dish_forecasts(db, 'S001', '2025-01',
                                                forecast_period='2025-03')
        assert result['forecast_period'] == '2025-03'

    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = _make_db([[]])
        result = await generate_dish_forecasts(db, 'S001', '2025-01')
        assert result['dish_count'] == 0
        assert result['total_predicted_revenue'] == 0.0

    @pytest.mark.asyncio
    async def test_phase_counts_populated(self):
        hist_rows = [
            _hist_row('D001', '宫保鸡丁', '2025-01', 120, 4560.0),
            _hist_row('D002', '清蒸鱼',   '2025-01',   8,  320.0),
        ]
        lc_rows = [('D001', 'peak'), ('D002', 'decline')]
        db = _make_db([hist_rows, lc_rows])
        result = await generate_dish_forecasts(db, 'S001', '2025-01')
        assert 'peak' in result['phase_counts'] or 'decline' in result['phase_counts']


# ── TestGetDishForecasts ──────────────────────────────────────────────────────
class TestGetDishForecasts:
    def _row(self, phase='peak'):
        return (
            1, 'D001', '宫保鸡丁', '热菜', phase,
            4, 115.0, 4370.0, 5.0, 5.0, 0.0,
            120.8, 108.7, 132.8,
            4588.0, 4129.2, 5046.8,
            30.0, 62.0, '2025-01',
        )

    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = _make_db([[self._row()]])
        recs = await get_dish_forecasts(db, 'S001', '2025-02')
        assert len(recs) == 1
        assert recs[0]['lifecycle_phase'] == 'peak'

    @pytest.mark.asyncio
    async def test_phase_filter(self):
        db = _make_db([[self._row('growth')]])
        recs = await get_dish_forecasts(db, 'S001', '2025-02',
                                         lifecycle_phase='growth')
        assert len(recs) == 1
        assert recs[0]['lifecycle_phase'] == 'growth'

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        recs = await get_dish_forecasts(db, 'S001', '2025-02')
        assert recs == []


# ── TestGetForecastSummary ────────────────────────────────────────────────────
class TestGetForecastSummary:
    @pytest.mark.asyncio
    async def test_aggregation(self):
        rows = [
            ('peak',    6, 720.0, 27360.0, 3.2, 0.0, 5.5),
            ('growth',  3, 330.0, 12540.0, 8.5, 10.0, 4.0),
            ('decline', 2, 160.0,  5120.0, -6.2, -8.0, 3.5),
        ]
        db = _make_db([rows])
        result = await get_forecast_summary(db, 'S001', '2025-02')
        assert result['total_dishes'] == 11
        assert result['total_revenue'] == pytest.approx(45020.0, abs=1.0)
        assert len(result['by_phase']) == 3

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        result = await get_forecast_summary(db, 'S001', '2025-02')
        assert result['total_dishes'] == 0
        assert result['total_revenue'] == 0.0


# ── TestGetForecastAccuracy ───────────────────────────────────────────────────
class TestGetForecastAccuracy:
    @pytest.mark.asyncio
    async def test_returns_accuracy(self):
        row = ('D001', '宫保鸡丁', '热菜', 'peak',
               120.0, 4560.0, 115, 4370.0, -4.2, -4.2)
        db = _make_db([[row]])
        results = await get_forecast_accuracy(db, 'S001', '2025-01')
        assert len(results) == 1
        assert results[0]['dish_name'] == '宫保鸡丁'
        assert results[0]['order_error_pct'] == pytest.approx(-4.2, abs=0.1)

    @pytest.mark.asyncio
    async def test_empty_when_no_actual_data(self):
        db = _make_db([[]])
        results = await get_forecast_accuracy(db, 'S001', '2025-06')
        assert results == []


# ── TestGetDishForecastHistory ────────────────────────────────────────────────
class TestGetDishForecastHistory:
    @pytest.mark.asyncio
    async def test_returns_history_with_actuals(self):
        rows = [
            ('2025-02', '2025-01', 'peak', 120.8, 108.7, 132.8,
             4588.0, 4129.2, 5046.8, 5.0, 0.0, 4, 115, 4370.0),
            ('2025-01', '2024-12', 'growth', 110.2, 99.2, 121.2,
             4187.6, 3768.8, 4606.4, 8.5, 10.0, 3, 112, 4256.0),
        ]
        db = _make_db([rows])
        history = await get_dish_forecast_history(db, 'S001', 'D001')
        assert len(history) == 2
        assert history[0]['forecast_period'] == '2025-02'
        assert history[0]['actual_revenue'] == pytest.approx(4370.0, abs=0.1)
        assert history[1]['actual_orders'] == 112

    @pytest.mark.asyncio
    async def test_no_actual_data_left_join_null(self):
        rows = [
            ('2025-02', '2025-01', 'peak', 120.8, 108.7, 132.8,
             4588.0, 4129.2, 5046.8, 5.0, 0.0, 4, None, None),
        ]
        db = _make_db([rows])
        history = await get_dish_forecast_history(db, 'S001', 'D001')
        assert len(history) == 1
        assert history[0]['actual_revenue'] is None

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        history = await get_dish_forecast_history(db, 'S001', 'D999')
        assert history == []
