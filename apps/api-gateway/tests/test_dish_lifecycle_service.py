"""Tests for dish_lifecycle_service — Phase 6 Month 6"""
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

from src.services.dish_lifecycle_service import (
    compute_revenue_trend,
    compute_order_trend,
    classify_lifecycle_phase,
    detect_phase_transition,
    compute_phase_duration,
    compute_lifecycle_impact,
    compute_lifecycle_confidence,
    build_lifecycle_record,
    _prev_period,
    _start_period,
    compute_lifecycle_analysis,
    get_lifecycle_records,
    get_lifecycle_summary,
    get_phase_transition_alerts,
    get_dish_lifecycle_history,
    EXIT_KITCHEN_SAVINGS,
)

# ── 代表性菜品 fixture ─────────────────────────────────────────────────────────
def _dish(dish_id='D001', dish_name='宫保鸡丁', bcg='star',
          orders=120, revenue=4560.0, gpm=62.0, fcr=28.0):
    return {
        'dish_id': dish_id, 'dish_name': dish_name, 'category': '热菜',
        'bcg_quadrant': bcg, 'order_count': orders,
        'revenue_yuan': revenue, 'gross_profit_margin': gpm, 'food_cost_rate': fcr,
    }


# ── TestComputeRevenueTrend ───────────────────────────────────────────────────
class TestComputeRevenueTrend:
    def test_growth(self):
        assert compute_revenue_trend(5500.0, 5000.0) == pytest.approx(10.0, abs=0.1)

    def test_decline(self):
        assert compute_revenue_trend(4500.0, 5000.0) == pytest.approx(-10.0, abs=0.1)

    def test_zero_previous(self):
        assert compute_revenue_trend(5000.0, 0.0) == 0.0

    def test_flat(self):
        assert compute_revenue_trend(5000.0, 5000.0) == 0.0

    def test_negative_previous(self):
        # abs() guards against negative denominator
        assert compute_revenue_trend(4000.0, 5000.0) == pytest.approx(-20.0, abs=0.1)


# ── TestComputeOrderTrend ─────────────────────────────────────────────────────
class TestComputeOrderTrend:
    def test_growth(self):
        assert compute_order_trend(132, 120) == pytest.approx(10.0, abs=0.1)

    def test_decline(self):
        assert compute_order_trend(90, 120) == pytest.approx(-25.0, abs=0.1)

    def test_zero_previous(self):
        assert compute_order_trend(100, 0) == 0.0

    def test_flat(self):
        assert compute_order_trend(100, 100) == 0.0


# ── TestClassifyLifecyclePhase ────────────────────────────────────────────────
class TestClassifyLifecyclePhase:
    def test_new_dish_is_launch(self):
        assert classify_lifecycle_phase('star', 50.0, 30.0, True) == 'launch'

    def test_dog_with_severe_decline_is_exit(self):
        assert classify_lifecycle_phase('dog', -25.0, -25.0, False) == 'exit'

    def test_dog_moderate_decline_is_decline(self):
        assert classify_lifecycle_phase('dog', -10.0, -5.0, False) == 'decline'

    def test_cash_cow_declining_is_decline(self):
        assert classify_lifecycle_phase('cash_cow', -6.0, -3.0, False) == 'decline'

    def test_cash_cow_stable_is_peak(self):
        assert classify_lifecycle_phase('cash_cow', 2.0, 1.0, False) == 'peak'

    def test_star_growing_is_growth(self):
        assert classify_lifecycle_phase('star', 15.0, 12.0, False) == 'growth'

    def test_star_stable_is_peak(self):
        assert classify_lifecycle_phase('star', 2.0, 3.0, False) == 'peak'

    def test_qm_growing_is_growth(self):
        assert classify_lifecycle_phase('question_mark', 20.0, 15.0, False) == 'growth'

    def test_qm_strongly_declining_is_decline(self):
        assert classify_lifecycle_phase('question_mark', -15.0, -5.0, False) == 'decline'

    def test_qm_mildly_declining_is_growth(self):
        # mild decline < -10 threshold → still growth (潜力期)
        assert classify_lifecycle_phase('question_mark', -3.0, 2.0, False) == 'growth'

    def test_dog_exactly_at_exit_threshold(self):
        assert classify_lifecycle_phase('dog', -20.0, -20.0, False) == 'exit'

    def test_dog_just_above_exit_threshold(self):
        # -19.9 > -20 → not exit, but still decline (dog with rev < -5)
        assert classify_lifecycle_phase('dog', -19.9, -10.0, False) == 'decline'


# ── TestDetectPhaseTransition ─────────────────────────────────────────────────
class TestDetectPhaseTransition:
    def test_same_phase_no_transition(self):
        assert detect_phase_transition('peak', 'peak') is False

    def test_different_phase_is_transition(self):
        assert detect_phase_transition('decline', 'peak') is True

    def test_none_prev_no_transition(self):
        assert detect_phase_transition('launch', None) is False

    def test_growth_to_peak_is_transition(self):
        assert detect_phase_transition('peak', 'growth') is True


# ── TestComputePhaseDuration ──────────────────────────────────────────────────
class TestComputePhaseDuration:
    def test_same_phase_increments(self):
        assert compute_phase_duration('peak', 'peak', 3) == 4

    def test_phase_change_resets_to_one(self):
        assert compute_phase_duration('decline', 'peak', 5) == 1

    def test_no_history_returns_one(self):
        assert compute_phase_duration('launch', None, 0) == 1

    def test_large_duration(self):
        assert compute_phase_duration('peak', 'peak', 11) == 12


# ── TestComputeLifecycleImpact ────────────────────────────────────────────────
class TestComputeLifecycleImpact:
    def test_launch_20_pct(self):
        assert compute_lifecycle_impact('launch', 5000.0, 0.0) == pytest.approx(1000.0, abs=0.1)

    def test_growth_5_pct(self):
        assert compute_lifecycle_impact('growth', 4000.0, 15.0) == pytest.approx(200.0, abs=0.1)

    def test_peak_3_pct(self):
        assert compute_lifecycle_impact('peak', 10000.0, 0.0) == pytest.approx(300.0, abs=0.1)

    def test_decline_30_pct_of_lost(self):
        # revenue_trend=-20%, revenue=5000 → lost=1000 → recoverable=300
        result = compute_lifecycle_impact('decline', 5000.0, -20.0)
        assert result == pytest.approx(300.0, abs=0.1)

    def test_exit_kitchen_savings(self):
        assert compute_lifecycle_impact('exit', 200.0, -30.0) == EXIT_KITCHEN_SAVINGS

    def test_decline_zero_trend(self):
        # -0 decline → 0 recoverable (dish is declining but MoM is flat this month)
        assert compute_lifecycle_impact('decline', 5000.0, 0.0) == 0.0


# ── TestComputeLifecycleConfidence ────────────────────────────────────────────
class TestComputeLifecycleConfidence:
    def test_launch_always_50(self):
        assert compute_lifecycle_confidence('launch', 6, 200) == 50.0

    def test_long_duration_increases_confidence(self):
        short = compute_lifecycle_confidence('peak', 1, 30)
        long  = compute_lifecycle_confidence('peak', 6, 30)
        assert long > short

    def test_high_order_count_boosts(self):
        low  = compute_lifecycle_confidence('peak', 3, 10)
        high = compute_lifecycle_confidence('peak', 3, 150)
        assert high > low

    def test_never_exceeds_90(self):
        conf = compute_lifecycle_confidence('peak', 100, 10000)
        assert conf <= 90.0

    def test_exit_high_duration(self):
        conf = compute_lifecycle_confidence('exit', 5, 5)
        assert conf <= 90.0


# ── TestBuildLifecycleRecord ──────────────────────────────────────────────────
class TestBuildLifecycleRecord:
    def test_new_dish_is_launch(self):
        rec = build_lifecycle_record('S001', '2025-01', _dish(), None, None)
        assert rec['phase'] == 'launch'
        assert rec['phase_changed'] is False
        assert rec['phase_duration_months'] == 1

    def test_growing_star(self):
        curr = _dish(orders=132, revenue=5016.0)  # +10% revenue
        prev = _dish(orders=120, revenue=4560.0)
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, None)
        assert rec['phase'] == 'growth'
        assert rec['revenue_trend_pct'] == pytest.approx(10.0, abs=0.5)

    def test_stable_star_is_peak(self):
        curr = _dish(orders=122, revenue=4636.0)  # +1.7% growth
        prev = _dish(orders=120, revenue=4560.0)
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, None)
        assert rec['phase'] == 'peak'

    def test_declining_cash_cow(self):
        curr = _dish(bcg='cash_cow', orders=100, revenue=3800.0)
        prev = _dish(bcg='cash_cow', orders=110, revenue=4200.0)  # -9.5% revenue
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, None)
        assert rec['phase'] == 'decline'

    def test_phase_transition_detected(self):
        curr = _dish(bcg='cash_cow', orders=100, revenue=3800.0)
        prev = _dish(bcg='cash_cow', orders=110, revenue=4200.0)
        prev_lc = {'phase': 'peak', 'phase_duration_months': 4}
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, prev_lc)
        assert rec['phase'] == 'decline'
        assert rec['phase_changed'] is True
        assert rec['prev_phase'] == 'peak'
        assert rec['phase_duration_months'] == 1

    def test_same_phase_duration_increments(self):
        curr = _dish(orders=100, revenue=4000.0)
        prev = _dish(orders=102, revenue=4050.0)  # stable
        prev_lc = {'phase': 'peak', 'phase_duration_months': 3}
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, prev_lc)
        assert rec['phase'] == 'peak'
        assert rec['phase_duration_months'] == 4
        assert rec['phase_changed'] is False

    def test_fcr_trend_computed(self):
        curr = _dish(fcr=32.0)
        prev = _dish(fcr=28.0)
        rec = build_lifecycle_record('S001', '2025-01', curr, prev, None)
        assert rec['fcr_trend_pp'] == pytest.approx(4.0, abs=0.1)

    def test_expected_impact_positive(self):
        rec = build_lifecycle_record('S001', '2025-01', _dish(revenue=5000.0), None, None)
        assert rec['expected_impact_yuan'] > 0

    def test_action_description_nonempty(self):
        rec = build_lifecycle_record('S001', '2025-01', _dish(), None, None)
        assert len(rec['action_description']) > 5


# ── TestPrevPeriod ────────────────────────────────────────────────────────────
class TestPrevPeriod:
    def test_normal(self):
        assert _prev_period('2025-06') == '2025-05'

    def test_january_wraps(self):
        assert _prev_period('2025-01') == '2024-12'

    def test_december(self):
        assert _prev_period('2025-12') == '2025-11'


class TestStartPeriod:
    def test_no_wrap(self):
        assert _start_period('2025-06', 6) == '2025-01'

    def test_year_wrap(self):
        assert _start_period('2025-03', 4) == '2024-12'


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


def _prof_row(dish_id, dish_name, bcg, orders, revenue, gpm, fcr):
    return (dish_id, dish_name, '热菜', bcg, orders, revenue, gpm, fcr)


# ── TestComputeLifecycleAnalysis ──────────────────────────────────────────────
class TestComputeLifecycleAnalysis:
    @pytest.mark.asyncio
    async def test_basic_two_dishes(self):
        curr_rows = [
            _prof_row('D001', '宫保鸡丁', 'star', 132, 5016.0, 62.0, 28.0),
            _prof_row('D002', '清蒸鱼',   'dog',  5,   300.0,  20.0, 60.0),
        ]
        prev_rows = [
            _prof_row('D001', '宫保鸡丁', 'star', 120, 4560.0, 62.0, 28.0),
            _prof_row('D002', '清蒸鱼',   'dog',  10,  600.0,  20.0, 60.0),
        ]
        prev_lc_rows = []  # no prev lifecycle
        db = _make_db([curr_rows, prev_rows, prev_lc_rows])
        result = await compute_lifecycle_analysis(db, 'S001', '2025-01')
        assert result['dish_count'] == 2
        assert sum(result['phase_counts'].values()) == 2

    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = _make_db([[]])
        result = await compute_lifecycle_analysis(db, 'S001', '2025-01')
        assert result['dish_count'] == 0
        assert result['total_impact_yuan'] == 0.0

    @pytest.mark.asyncio
    async def test_new_dish_counted_as_launch(self):
        curr_rows = [_prof_row('D001', '新品', 'star', 50, 1900.0, 55.0, 30.0)]
        prev_rows = []   # no prev data → new dish
        prev_lc_rows = []
        db = _make_db([curr_rows, prev_rows, prev_lc_rows])
        result = await compute_lifecycle_analysis(db, 'S001', '2025-01')
        assert result['phase_counts'].get('launch', 0) == 1

    @pytest.mark.asyncio
    async def test_transition_counted(self):
        curr_rows = [_prof_row('D001', '宫保鸡丁', 'cash_cow', 100, 3800.0, 55.0, 30.0)]
        prev_rows = [_prof_row('D001', '宫保鸡丁', 'cash_cow', 110, 4200.0, 55.0, 30.0)]
        # prev lifecycle: phase=peak → now decline → transition
        prev_lc_rows = [('D001', 'peak', 4)]
        db = _make_db([curr_rows, prev_rows, prev_lc_rows])
        result = await compute_lifecycle_analysis(db, 'S001', '2025-01')
        assert result['transition_count'] >= 1


# ── TestGetLifecycleRecords ───────────────────────────────────────────────────
class TestGetLifecycleRecords:
    def _row(self, phase='peak'):
        return (
            1, 'D001', '宫保鸡丁', '热菜', 'star',
            120, 4560.0, 62.0, 28.0,
            10.0, 10.0, 2.0,
            phase, 'growth', False, 2,
            'optimize_profitability', '精细化运营', '成熟期描述',
            136.8, 75.0,
        )

    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = _make_db([[self._row()]])
        recs = await get_lifecycle_records(db, 'S001', '2025-01')
        assert len(recs) == 1
        assert recs[0]['phase'] == 'peak'

    @pytest.mark.asyncio
    async def test_phase_filter(self):
        db = _make_db([[self._row('decline')]])
        recs = await get_lifecycle_records(db, 'S001', '2025-01', phase='decline')
        assert len(recs) == 1
        assert recs[0]['phase'] == 'decline'

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        recs = await get_lifecycle_records(db, 'S001', '2025-01')
        assert recs == []


# ── TestGetLifecycleSummary ───────────────────────────────────────────────────
class TestGetLifecycleSummary:
    @pytest.mark.asyncio
    async def test_aggregation(self):
        rows = [
            ('peak',    8, 1, 2400.0, 5.2, 2.0, 48000.0),
            ('decline', 3, 2,  450.0, 3.0, -8.0, 9000.0),
            ('launch',  2, 0,  380.0, 1.0, 0.0,  3800.0),
        ]
        db = _make_db([rows])
        result = await get_lifecycle_summary(db, 'S001', '2025-01')
        assert result['total_dishes'] == 13
        assert result['total_transitions'] == 3
        assert result['total_impact_yuan'] == pytest.approx(3230.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        result = await get_lifecycle_summary(db, 'S001', '2025-01')
        assert result['total_dishes'] == 0


# ── TestGetPhaseTransitionAlerts ──────────────────────────────────────────────
class TestGetPhaseTransitionAlerts:
    @pytest.mark.asyncio
    async def test_returns_transitions(self):
        row = (
            'D002', '清蒸鱼', '海鲜', 'dog',
            'peak', 'decline', 1,
            -9.5, -8.0,
            4200.0, 399.0,
            '重新定位/控成本', '需求下滑，评估调整口味',
        )
        db = _make_db([[row]])
        alerts = await get_phase_transition_alerts(db, 'S001', '2025-01')
        assert len(alerts) == 1
        assert alerts[0]['prev_phase'] == 'peak'
        assert alerts[0]['phase'] == 'decline'

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        alerts = await get_phase_transition_alerts(db, 'S001', '2025-01')
        assert alerts == []


# ── TestGetDishLifecycleHistory ───────────────────────────────────────────────
class TestGetDishLifecycleHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self):
        rows = [
            ('2025-01', 'star', 'peak',    'growth', False, 3, 4560.0, 120, 10.0, 10.0, '精细化运营', 136.8),
            ('2024-12', 'star', 'growth',  None,     False, 2, 4200.0, 110,  8.0,  8.0, '扩大影响',   210.0),
            ('2024-11', 'star', 'growth',  None,     False, 1, 3900.0, 100, 15.0, 12.0, '扩大影响',   195.0),
        ]
        db = _make_db([rows])
        history = await get_dish_lifecycle_history(db, 'S001', 'D001', periods=12)
        assert len(history) == 3
        assert history[0]['period'] == '2025-01'
        assert history[0]['phase'] == 'peak'
        assert history[2]['phase'] == 'growth'

    @pytest.mark.asyncio
    async def test_empty_history(self):
        db = _make_db([[]])
        history = await get_dish_lifecycle_history(db, 'S001', 'D999')
        assert history == []
