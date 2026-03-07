"""tests/test_dish_cost_compression_service.py — Phase 6 Month 11"""

import pytest
from unittest.mock import MagicMock, AsyncMock

import src.core.config  # noqa: F401

from src.services.dish_cost_compression_service import (
    _prev_period,
    compute_target_fcr,
    compute_fcr_gap,
    compute_compression_opportunity,
    compute_expected_saving,
    classify_fcr_trend,
    determine_compression_action,
    determine_priority,
    build_compression_record,
    compute_cost_compression,
    get_cost_compression,
    get_compression_summary,
    get_top_opportunities,
    get_dish_fcr_history,
)


# ── _prev_period ──────────────────────────────────────────────────────────────

class TestPrevPeriod:
    def test_mid_year(self):
        assert _prev_period('2025-07') == '2025-06'

    def test_january(self):
        assert _prev_period('2025-01') == '2024-12'


# ── compute_target_fcr ────────────────────────────────────────────────────────

class TestComputeTargetFcr:
    def test_normal(self):
        assert compute_target_fcr(35.0, 2.0) == 33.0

    def test_floor(self):
        # 22 - 5 = 17 < 20 → clamped to 20
        assert compute_target_fcr(22.0, 5.0) == 20.0

    def test_exact_floor(self):
        assert compute_target_fcr(22.0, 2.0) == 20.0

    def test_default_reduction(self):
        assert compute_target_fcr(40.0) == 38.0


# ── compute_fcr_gap ───────────────────────────────────────────────────────────

class TestComputeFcrGap:
    def test_positive(self):
        assert compute_fcr_gap(35.0, 33.0) == 2.0

    def test_negative(self):
        assert compute_fcr_gap(30.0, 33.0) == -3.0

    def test_zero(self):
        assert compute_fcr_gap(33.0, 33.0) == 0.0


# ── compute_compression_opportunity ──────────────────────────────────────────

class TestComputeCompressionOpportunity:
    def test_positive_gap(self):
        # revenue 10000, gap 3% → 300
        assert compute_compression_opportunity(10000.0, 3.0) == 300.0

    def test_zero_gap(self):
        assert compute_compression_opportunity(10000.0, 0.0) == 0.0

    def test_negative_gap(self):
        assert compute_compression_opportunity(10000.0, -2.0) == 0.0

    def test_rounding(self):
        assert compute_compression_opportunity(333.33, 1.0) == 3.33


# ── compute_expected_saving ───────────────────────────────────────────────────

class TestComputeExpectedSaving:
    def test_annual(self):
        assert compute_expected_saving(300.0) == 3600.0

    def test_custom_months(self):
        assert compute_expected_saving(300.0, months=6) == 1800.0

    def test_zero(self):
        assert compute_expected_saving(0.0) == 0.0


# ── classify_fcr_trend ────────────────────────────────────────────────────────

class TestClassifyFcrTrend:
    def test_improving(self):
        assert classify_fcr_trend(30.0, 32.0) == 'improving'

    def test_worsening(self):
        assert classify_fcr_trend(35.0, 33.0) == 'worsening'

    def test_stable_small_diff(self):
        assert classify_fcr_trend(33.5, 33.0) == 'stable'

    def test_no_prev(self):
        assert classify_fcr_trend(33.0, None) == 'stable'

    def test_exactly_1pp_up(self):
        # diff = 1.0, NOT > 1.0 → stable
        assert classify_fcr_trend(34.0, 33.0) == 'stable'

    def test_boundary_worsening(self):
        assert classify_fcr_trend(34.1, 33.0) == 'worsening'


# ── determine_compression_action ─────────────────────────────────────────────

class TestDetermineCompressionAction:
    def test_monitor_no_gap(self):
        assert determine_compression_action(0.0, 'stable') == 'monitor'

    def test_monitor_negative(self):
        assert determine_compression_action(-2.0, 'stable') == 'monitor'

    def test_renegotiate(self):
        assert determine_compression_action(6.0, 'worsening') == 'renegotiate'

    def test_reformulate(self):
        assert determine_compression_action(4.0, 'stable') == 'reformulate'

    def test_adjust_portion(self):
        assert determine_compression_action(2.0, 'stable') == 'adjust_portion'

    def test_monitor_small_gap(self):
        assert determine_compression_action(0.5, 'stable') == 'monitor'

    def test_renegotiate_requires_worsening(self):
        # gap > 5 but NOT worsening → reformulate
        assert determine_compression_action(6.0, 'stable') == 'reformulate'


# ── determine_priority ────────────────────────────────────────────────────────

class TestDeterminePriority:
    def test_high_large_opportunity(self):
        assert determine_priority(1500.0, 'stable') == 'high'

    def test_high_mid_opportunity_worsening(self):
        assert determine_priority(600.0, 'worsening') == 'high'

    def test_medium(self):
        assert determine_priority(300.0, 'stable') == 'medium'

    def test_low(self):
        assert determine_priority(100.0, 'stable') == 'low'

    def test_boundary_medium(self):
        # 200 is NOT > 200 → low
        assert determine_priority(200.0, 'stable') == 'low'

    def test_boundary_medium_above(self):
        assert determine_priority(201.0, 'stable') == 'medium'


# ── build_compression_record ──────────────────────────────────────────────────

class TestBuildCompressionRecord:
    def _make(self, current_fcr=38.0, prev_fcr=36.0,
              revenue=10000.0, target_fcr=33.0, store_avg=35.0):
        return build_compression_record(
            'S001', '2025-06',
            'D001', '红烧肉', '主菜',
            revenue, 100,
            current_fcr, 62.0,
            target_fcr, store_avg,
            prev_fcr,
        )

    def test_keys_present(self):
        r = self._make()
        for k in ['store_id', 'period', 'dish_id', 'dish_name', 'category',
                  'revenue_yuan', 'order_count', 'current_fcr', 'current_gpm',
                  'target_fcr', 'store_avg_fcr', 'fcr_gap',
                  'compression_opportunity_yuan', 'expected_saving_yuan',
                  'prev_fcr', 'fcr_trend', 'compression_action', 'action_priority']:
            assert k in r

    def test_fcr_gap(self):
        r = self._make(current_fcr=38.0, target_fcr=33.0)
        assert r['fcr_gap'] == 5.0

    def test_opportunity_calculation(self):
        r = self._make(current_fcr=38.0, target_fcr=33.0, revenue=10000.0)
        assert r['compression_opportunity_yuan'] == 500.0

    def test_annual_saving(self):
        r = self._make(current_fcr=38.0, target_fcr=33.0, revenue=10000.0)
        assert r['expected_saving_yuan'] == 6000.0

    def test_worsening_triggers_renegotiate(self):
        r = self._make(current_fcr=40.0, prev_fcr=33.0)  # diff = 7 > 1 → worsening
        assert r['fcr_trend'] == 'worsening'
        # gap = 40 - 33 = 7 > 5, worsening → renegotiate
        assert r['compression_action'] == 'renegotiate'

    def test_no_prev_fcr(self):
        r = build_compression_record(
            'S001', '2025-06', 'D001', '菜A', None,
            5000.0, 50, 35.0, None, 33.0, 35.0, None,
        )
        assert r['prev_fcr'] is None
        assert r['fcr_trend'] == 'stable'

    def test_below_target(self):
        r = self._make(current_fcr=30.0, target_fcr=33.0)
        assert r['fcr_gap'] == -3.0
        assert r['compression_opportunity_yuan'] == 0.0
        assert r['compression_action'] == 'monitor'


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_db(call_returns: list):
    returns_iter = iter(call_returns)
    db = MagicMock()
    db.commit = AsyncMock()

    async def _execute(sql, params=None):
        try:
            rows = next(returns_iter)
        except StopIteration:
            rows = []
        result = MagicMock()
        result.fetchall.return_value = rows
        return result

    db.execute = _execute
    return db


# ── compute_cost_compression ──────────────────────────────────────────────────

class TestComputeCostCompression:
    @pytest.mark.asyncio
    async def test_basic(self):
        curr = [
            ('D001', '红烧肉', '主菜', 100, 10000.0, 38.0, 62.0),
            ('D002', '炒饭',   '主食',  80,  4000.0, 32.0, 68.0),
        ]
        prev = [('D001', '红烧肉', '主菜', 80, 8000.0, 36.0, 64.0)]
        db = _make_db([curr, prev, [], []])
        result = await compute_cost_compression(db, 'S001', '2025-06')
        assert result['dish_count'] == 2
        assert result['store_avg_fcr'] == 35.0    # (38+32)/2
        assert result['target_fcr'] == 33.0        # 35 - 2

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[], []])
        result = await compute_cost_compression(db, 'S001', '2025-06')
        assert result['dish_count'] == 0

    @pytest.mark.asyncio
    async def test_default_prev_period(self):
        db = _make_db([[], []])
        result = await compute_cost_compression(db, 'S001', '2025-03')
        # Just verify it doesn't error; prev period computed internally

    @pytest.mark.asyncio
    async def test_custom_reduction(self):
        curr = [('D001', '菜A', None, 50, 5000.0, 40.0, 60.0)]
        prev: list = []
        db = _make_db([curr, prev, []])
        result = await compute_cost_compression(db, 'S001', '2025-06',
                                                target_fcr_reduction=3.0)
        assert result['target_fcr'] == 37.0   # 40 - 3


# ── get_cost_compression ──────────────────────────────────────────────────────

class TestGetCostCompression:
    def _row(self):
        return (1, 'D001', '红烧肉', '主菜',
                10000.0, 100,
                38.0, 62.0, 33.0, 35.0,
                5.0, 500.0, 6000.0,
                36.0, 'worsening', 'renegotiate', 'high')

    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = _make_db([[self._row()]])
        result = await get_cost_compression(db, 'S001', '2025-06')
        assert len(result) == 1
        assert result[0]['compression_action'] == 'renegotiate'

    @pytest.mark.asyncio
    async def test_action_filter(self):
        db = _make_db([[self._row()]])
        result = await get_cost_compression(db, 'S001', '2025-06',
                                             action='renegotiate')
        assert result[0]['action_priority'] == 'high'

    @pytest.mark.asyncio
    async def test_priority_filter(self):
        db = _make_db([[self._row()]])
        result = await get_cost_compression(db, 'S001', '2025-06',
                                             priority='high')
        assert len(result) == 1


# ── get_compression_summary ───────────────────────────────────────────────────

class TestGetCompressionSummary:
    @pytest.mark.asyncio
    async def test_basic(self):
        action_rows = [
            ('renegotiate',   2, 2000.0, 24000.0, 6.5, 2),
            ('reformulate',   5, 1500.0, 18000.0, 4.0, 1),
            ('adjust_portion', 8, 800.0, 9600.0,  2.0, 0),
            ('monitor',       10, 0.0,      0.0,   0.0, 0),
        ]
        trend_rows = [
            ('improving',  5, 500.0, 30.0, -1.5),
            ('stable',    15, 2800.0, 35.0, 3.0),
            ('worsening',  5, 1000.0, 40.0, 7.0),
        ]
        db = _make_db([action_rows, trend_rows])
        result = await get_compression_summary(db, 'S001', '2025-06')
        assert len(result['by_action']) == 4
        assert len(result['by_trend']) == 3
        assert result['total_opportunity_yuan'] == 4300.0

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[], []])
        result = await get_compression_summary(db, 'S001', '2025-06')
        assert result['total_opportunity_yuan'] == 0.0


# ── get_top_opportunities ─────────────────────────────────────────────────────

class TestGetTopOpportunities:
    @pytest.mark.asyncio
    async def test_basic(self):
        row = ('D001', '红烧肉', '主菜',
               38.0, 33.0, 5.0, 500.0, 6000.0,
               'worsening', 'renegotiate', 'high', 10000.0)
        db = _make_db([[row]])
        result = await get_top_opportunities(db, 'S001', '2025-06')
        assert len(result) == 1
        assert result[0]['compression_opportunity_yuan'] == 500.0


# ── get_dish_fcr_history ──────────────────────────────────────────────────────

class TestGetDishFcrHistory:
    @pytest.mark.asyncio
    async def test_basic(self):
        rows = [
            ('2025-06', 38.0, 36.0, 5.0, 33.0, 35.0,
             'worsening', 'renegotiate', 'high', 500.0, 6000.0, 10000.0),
            ('2025-05', 36.0, 35.0, 3.0, 33.0, 34.0,
             'worsening', 'reformulate', 'medium', 300.0, 3600.0, 10000.0),
        ]
        db = _make_db([rows])
        result = await get_dish_fcr_history(db, 'S001', 'D001')
        assert len(result) == 2
        assert result[0]['period'] == '2025-06'
        assert result[0]['fcr_trend'] == 'worsening'
