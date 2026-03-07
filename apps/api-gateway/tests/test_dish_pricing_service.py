"""Tests for dish_pricing_service — Phase 6 Month 5"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys, types

cfg_mod = types.ModuleType("src.core.config")
cfg_mod.settings = MagicMock(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    redis_url="redis://localhost",
    secret_key="test",
)
sys.modules.setdefault("src.core.config", cfg_mod)
sys.modules.setdefault("src.core.database", types.ModuleType("src.core.database"))

from src.services.dish_pricing_service import (
    classify_price_elasticity,
    compute_price_recommendation,
    compute_demand_change,
    compute_revenue_delta,
    compute_profit_delta,
    compute_pricing_confidence,
    build_pricing_record,
    _start_period,
    generate_pricing_recommendations,
    get_pricing_recommendations,
    get_pricing_summary,
    update_pricing_status,
    get_pricing_history,
    STAR_PRICE_LIFT_PCT,
    CASH_COW_PRICE_LIFT_PCT,
    QUESTION_MARK_PRICE_DROP_PCT,
    HIGH_FCR_PRICE_LIFT_PCT,
)

# ── 代表性菜品 fixture ─────────────────────────────────────────────────────────
STAR_DISH = {
    'dish_id': 'D001', 'dish_name': '宫保鸡丁', 'category': '热菜',
    'bcg_quadrant': 'star', 'avg_selling_price': 38.0,
    'order_count': 120, 'revenue_yuan': 4560.0,
    'gross_profit_margin': 62.0, 'food_cost_rate': 28.0,
}
COW_DISH = {
    'dish_id': 'D002', 'dish_name': '麻婆豆腐', 'category': '热菜',
    'bcg_quadrant': 'cash_cow', 'avg_selling_price': 24.0,
    'order_count': 200, 'revenue_yuan': 4800.0,
    'gross_profit_margin': 55.0, 'food_cost_rate': 30.0,
}
QM_DISH = {
    'dish_id': 'D003', 'dish_name': '炖牛腩', 'category': '炖品',
    'bcg_quadrant': 'question_mark', 'avg_selling_price': 58.0,
    'order_count': 20, 'revenue_yuan': 1160.0,
    'gross_profit_margin': 45.0, 'food_cost_rate': 35.0,
}
DOG_DISH = {
    'dish_id': 'D004', 'dish_name': '清蒸鱼', 'category': '海鲜',
    'bcg_quadrant': 'dog', 'avg_selling_price': 88.0,
    'order_count': 8, 'revenue_yuan': 704.0,
    'gross_profit_margin': 25.0, 'food_cost_rate': 55.0,
}
HIGH_FCR_DISH = {
    'dish_id': 'D005', 'dish_name': '龙虾面', 'category': '面食',
    'bcg_quadrant': 'cash_cow', 'avg_selling_price': 68.0,
    'order_count': 40, 'revenue_yuan': 2720.0,
    'gross_profit_margin': 40.0, 'food_cost_rate': 45.0,
}


# ── TestClassifyPriceElasticity ───────────────────────────────────────────────
class TestClassifyPriceElasticity:
    def test_star_is_inelastic(self):
        assert classify_price_elasticity('star', 100, 80.0) == 'inelastic'

    def test_cash_cow_is_inelastic(self):
        assert classify_price_elasticity('cash_cow', 200, 80.0) == 'inelastic'

    def test_dog_is_elastic(self):
        assert classify_price_elasticity('dog', 10, 80.0) == 'elastic'

    def test_qm_high_orders_is_inelastic(self):
        # order_count >= store_avg * 1.2
        assert classify_price_elasticity('question_mark', 100, 80.0) == 'inelastic'

    def test_qm_low_orders_is_moderate(self):
        assert classify_price_elasticity('question_mark', 20, 80.0) == 'moderate'

    def test_qm_zero_avg_is_moderate(self):
        assert classify_price_elasticity('question_mark', 50, 0.0) == 'moderate'

    def test_qm_exactly_at_threshold(self):
        # 96 / 80 = 1.2 → inelastic
        assert classify_price_elasticity('question_mark', 96, 80.0) == 'inelastic'

    def test_qm_just_below_threshold(self):
        # 95 / 80 = 1.1875 < 1.2 → moderate
        assert classify_price_elasticity('question_mark', 95, 80.0) == 'moderate'


# ── TestComputePriceRecommendation ────────────────────────────────────────────
class TestComputePriceRecommendation:
    def test_star_high_gpm_increase(self):
        dish = {**STAR_DISH, 'current_price': 38.0}
        rec = compute_price_recommendation(dish)
        assert rec is not None
        assert rec['rec_action'] == 'increase'
        assert rec['price_change_pct'] == STAR_PRICE_LIFT_PCT
        assert abs(rec['suggested_price'] - 38.0 * 1.08) < 0.2

    def test_star_low_gpm_no_increase(self):
        dish = {**STAR_DISH, 'gross_profit_margin': 50.0, 'current_price': 38.0}
        rec = compute_price_recommendation(dish)
        # gpm < 55 → no star increase, may fall through to high-fcr if fcr>=42
        # food_cost_rate=28 < 42, so maintain
        assert rec is None

    def test_cash_cow_high_gpm_increase(self):
        dish = {**COW_DISH, 'current_price': 24.0}
        rec = compute_price_recommendation(dish)
        assert rec is not None
        assert rec['rec_action'] == 'increase'
        assert rec['price_change_pct'] == CASH_COW_PRICE_LIFT_PCT

    def test_cash_cow_low_gpm_no_increase(self):
        dish = {**COW_DISH, 'gross_profit_margin': 40.0, 'food_cost_rate': 30.0,
                'current_price': 24.0}
        rec = compute_price_recommendation(dish)
        # gpm < 45, fcr < 42 → None
        assert rec is None

    def test_question_mark_low_orders_decrease(self):
        dish = {**QM_DISH, 'current_price': 58.0}
        rec = compute_price_recommendation(dish)
        assert rec is not None
        assert rec['rec_action'] == 'decrease'
        assert rec['price_change_pct'] == QUESTION_MARK_PRICE_DROP_PCT

    def test_question_mark_high_orders_no_decrease(self):
        dish = {**QM_DISH, 'order_count': 50, 'current_price': 58.0}
        rec = compute_price_recommendation(dish)
        # orders=50 >= 30, fcr=35 < 42 → None
        assert rec is None

    def test_high_fcr_increase(self):
        dish = {**HIGH_FCR_DISH, 'current_price': 68.0}
        rec = compute_price_recommendation(dish)
        assert rec is not None
        assert rec['rec_action'] == 'increase'
        assert rec['price_change_pct'] == HIGH_FCR_PRICE_LIFT_PCT

    def test_dog_high_fcr_increase(self):
        # dog with high FCR → high FCR rule triggers
        dish = {**DOG_DISH, 'current_price': 88.0}
        rec = compute_price_recommendation(dish)
        # fcr=55 >= 42 → increase
        assert rec is not None
        assert rec['rec_action'] == 'increase'
        assert rec['price_change_pct'] == HIGH_FCR_PRICE_LIFT_PCT

    def test_zero_price_returns_none(self):
        dish = {**STAR_DISH, 'current_price': 0.0}
        assert compute_price_recommendation(dish) is None

    def test_reasoning_is_nonempty(self):
        dish = {**STAR_DISH, 'current_price': 38.0}
        rec = compute_price_recommendation(dish)
        assert rec is not None
        assert len(rec['reasoning']) > 5


# ── TestComputeDemandChange ───────────────────────────────────────────────────
class TestComputeDemandChange:
    def test_price_increase_inelastic(self):
        expected = compute_demand_change(100, 8.0, 'inelastic')
        assert abs(expected - 95.0) < 0.01

    def test_price_increase_elastic(self):
        expected = compute_demand_change(100, 8.0, 'elastic')
        assert abs(expected - 80.0) < 0.01

    def test_price_decrease_moderate(self):
        expected = compute_demand_change(100, -8.0, 'moderate')
        assert abs(expected - 115.0) < 0.01

    def test_no_change_returns_same(self):
        assert compute_demand_change(100, 0.0, 'moderate') == 100.0

    def test_price_decrease_elastic(self):
        expected = compute_demand_change(50, -8.0, 'elastic')
        assert abs(expected - 60.0) < 0.01


# ── TestComputeRevenueDelta ───────────────────────────────────────────────────
class TestComputeRevenueDelta:
    def test_price_increase_with_demand_drop(self):
        # 38 * 100 = 3800 old, 41.04 * 95 = 3898.8 new
        delta = compute_revenue_delta(38.0, 41.04, 100, 95.0)
        assert abs(delta - (41.04 * 95 - 38.0 * 100)) < 0.1

    def test_price_decrease_with_demand_increase(self):
        delta = compute_revenue_delta(58.0, 53.36, 20, 23.0)
        # 53.36 * 23 - 58 * 20 = 1227.28 - 1160 = 67.28
        assert abs(delta - (53.36 * 23 - 58.0 * 20)) < 0.1

    def test_maintain_price_zero_delta(self):
        delta = compute_revenue_delta(38.0, 38.0, 100, 100.0)
        assert delta == 0.0


# ── TestComputeProfitDelta ────────────────────────────────────────────────────
class TestComputeProfitDelta:
    def test_basic(self):
        result = compute_profit_delta(1000.0, 60.0)
        assert abs(result - 600.0) < 0.01

    def test_zero_revenue_delta(self):
        assert compute_profit_delta(0.0, 60.0) == 0.0

    def test_negative_revenue_delta(self):
        result = compute_profit_delta(-200.0, 50.0)
        assert abs(result - (-100.0)) < 0.01


# ── TestComputePricingConfidence ──────────────────────────────────────────────
class TestComputePricingConfidence:
    def test_maintain_always_90(self):
        assert compute_pricing_confidence('dog', 5, 'maintain') == 90.0

    def test_star_high_orders(self):
        conf = compute_pricing_confidence('star', 60, 'increase')
        assert conf == 85.0

    def test_star_low_orders(self):
        conf = compute_pricing_confidence('star', 20, 'increase')
        assert conf == 70.0

    def test_cash_cow_high_orders(self):
        conf = compute_pricing_confidence('cash_cow', 100, 'increase')
        assert conf == 85.0

    def test_qm_decent_orders(self):
        conf = compute_pricing_confidence('question_mark', 35, 'decrease')
        assert conf == 60.0

    def test_dog_low_confidence(self):
        conf = compute_pricing_confidence('dog', 5, 'increase')
        assert conf == 45.0

    def test_never_exceeds_95(self):
        conf = compute_pricing_confidence('star', 1000, 'increase')
        assert conf <= 95.0


# ── TestBuildPricingRecord ────────────────────────────────────────────────────
class TestBuildPricingRecord:
    def test_star_builds_increase_record(self):
        rec = build_pricing_record('S001', '2025-01', STAR_DISH, 80.0)
        assert rec['rec_action'] == 'increase'
        assert rec['store_id'] == 'S001'
        assert rec['period'] == '2025-01'
        assert rec['dish_id'] == 'D001'
        assert rec['elasticity_class'] == 'inelastic'
        assert rec['expected_profit_delta_yuan'] > 0

    def test_qm_low_orders_builds_decrease_record(self):
        rec = build_pricing_record('S001', '2025-01', QM_DISH, 80.0)
        assert rec['rec_action'] == 'decrease'
        assert rec['price_change_pct'] == QUESTION_MARK_PRICE_DROP_PCT

    def test_zero_price_falls_back_to_maintain(self):
        zero_price = {**STAR_DISH, 'avg_selling_price': 0.0}
        rec = build_pricing_record('S001', '2025-01', zero_price, 80.0)
        assert rec['rec_action'] == 'maintain'
        assert rec['price_change_pct'] == 0.0

    def test_maintain_reasoning_set(self):
        no_rec = {
            **COW_DISH,
            'gross_profit_margin': 40.0, 'food_cost_rate': 30.0,
        }
        rec = build_pricing_record('S001', '2025-01', no_rec, 80.0)
        assert rec['rec_action'] == 'maintain'
        assert rec['reasoning'] != ''

    def test_revenue_delta_computed(self):
        rec = build_pricing_record('S001', '2025-01', STAR_DISH, 80.0)
        # expected_revenue_delta_yuan should be a number
        assert isinstance(rec['expected_revenue_delta_yuan'], float)

    def test_profit_delta_positive_for_increase(self):
        rec = build_pricing_record('S001', '2025-01', STAR_DISH, 80.0)
        assert rec['expected_profit_delta_yuan'] > 0


# ── TestStartPeriod ───────────────────────────────────────────────────────────
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


def _prof_row(dish_id, dish_name, category, bcg, price, orders, revenue, gpm, fcr):
    return (dish_id, dish_name, category, bcg, price, orders, revenue, gpm, fcr)


# ── TestGeneratePricingRecommendations ────────────────────────────────────────
class TestGeneratePricingRecommendations:
    @pytest.mark.asyncio
    async def test_basic_generation(self):
        rows = [
            _prof_row('D001', '宫保鸡丁', '热菜', 'star', 38.0, 120, 4560.0, 62.0, 28.0),
            _prof_row('D002', '麻婆豆腐', '热菜', 'cash_cow', 24.0, 200, 4800.0, 55.0, 30.0),
            _prof_row('D003', '炖牛腩', '炖品', 'question_mark', 58.0, 20, 1160.0, 45.0, 35.0),
        ]
        db = _make_db([rows])
        result = await generate_pricing_recommendations(db, 'S001', '2025-01')
        assert result['dish_count'] == 3
        assert result['increase_count'] >= 2   # star + cash_cow
        assert result['decrease_count'] >= 1   # question_mark
        assert result['increase_count'] + result['decrease_count'] + result['maintain_count'] == 3

    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = _make_db([[]])
        result = await generate_pricing_recommendations(db, 'S001', '2025-01')
        assert result['dish_count'] == 0
        assert result['total_revenue_delta_yuan'] == 0.0

    @pytest.mark.asyncio
    async def test_revenue_delta_is_numeric(self):
        rows = [_prof_row('D001', '宫保鸡丁', '热菜', 'star', 38.0, 100, 3800.0, 62.0, 28.0)]
        db = _make_db([rows])
        result = await generate_pricing_recommendations(db, 'S001', '2025-01')
        assert isinstance(result['total_revenue_delta_yuan'], float)


# ── TestGetPricingRecommendations ─────────────────────────────────────────────
class TestGetPricingRecommendations:
    def _make_pricing_row(self, rec_action='increase', status='pending'):
        return (
            1, 'D001', '宫保鸡丁', '热菜', 'star',
            38.0, 120, 4560.0, 62.0, 28.0,
            rec_action, 41.04, 8.0, 'inelastic',
            114.0, 195.8, 121.4, 85.0, '明星菜提价',
            status, None, None, None,
        )

    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = _make_db([[self._make_pricing_row()]])
        recs = await get_pricing_recommendations(db, 'S001', '2025-01')
        assert len(recs) == 1
        assert recs[0]['rec_action'] == 'increase'

    @pytest.mark.asyncio
    async def test_rec_action_filter(self):
        db = _make_db([[self._make_pricing_row('decrease', 'pending')]])
        recs = await get_pricing_recommendations(db, 'S001', '2025-01',
                                                  rec_action='decrease')
        assert len(recs) == 1
        assert recs[0]['rec_action'] == 'decrease'

    @pytest.mark.asyncio
    async def test_status_filter(self):
        db = _make_db([[self._make_pricing_row('increase', 'adopted')]])
        recs = await get_pricing_recommendations(db, 'S001', '2025-01',
                                                  status='adopted')
        assert len(recs) == 1
        assert recs[0]['status'] == 'adopted'

    @pytest.mark.asyncio
    async def test_both_filters(self):
        db = _make_db([[self._make_pricing_row('increase', 'adopted')]])
        recs = await get_pricing_recommendations(db, 'S001', '2025-01',
                                                  rec_action='increase',
                                                  status='adopted')
        assert len(recs) == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        db = _make_db([[]])
        recs = await get_pricing_recommendations(db, 'S001', '2025-01')
        assert recs == []


# ── TestGetPricingSummary ─────────────────────────────────────────────────────
class TestGetPricingSummary:
    @pytest.mark.asyncio
    async def test_aggregation(self):
        rows = [
            ('increase', 5, 2, 2, 1, 500.0, 310.0, 80.0),
            ('decrease', 2, 1, 0, 1, 80.0,  36.0,  55.0),
            ('maintain', 8, 8, 0, 0, 0.0,   0.0,   90.0),
        ]
        db = _make_db([rows])
        result = await get_pricing_summary(db, 'S001', '2025-01')
        assert result['total_dishes'] == 15
        assert result['total_adopted'] == 2
        assert abs(result['adoption_rate'] - 2/15*100) < 0.1
        assert len(result['by_action']) == 3

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        result = await get_pricing_summary(db, 'S001', '2025-01')
        assert result['total_dishes'] == 0
        assert result['adoption_rate'] == 0.0


# ── TestUpdatePricingStatus ───────────────────────────────────────────────────
class TestUpdatePricingStatus:
    @pytest.mark.asyncio
    async def test_adopt_success(self):
        db = _make_db([None])
        result = await update_pricing_status(db, 1, 'adopt', adopted_price=41.0)
        assert result['updated'] is True
        assert result['action'] == 'adopt'

    @pytest.mark.asyncio
    async def test_dismiss_success(self):
        db = _make_db([None])
        result = await update_pricing_status(db, 2, 'dismiss')
        assert result['updated'] is True
        assert result['action'] == 'dismiss'

    @pytest.mark.asyncio
    async def test_not_found_returns_not_updated(self):
        db = AsyncMock()
        async def execute(sql, params=None):
            result = MagicMock()
            result.rowcount = 0
            return result
        db.execute = execute
        db.commit = AsyncMock()

        result = await update_pricing_status(db, 999, 'adopt')
        assert result['updated'] is False
        assert result['reason'] is not None


# ── TestGetPricingHistory ─────────────────────────────────────────────────────
class TestGetPricingHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self):
        rows = [
            ('2025-01', 41.04, 38.0, 8.0, 'increase', 'inelastic',
             195.8, 121.4, 85.0, 'adopted', 41.04),
            ('2024-12', 38.0, 36.0, 5.0, 'increase', 'inelastic',
             120.0, 74.4, 80.0, 'pending', None),
        ]
        db = _make_db([rows])
        history = await get_pricing_history(db, 'S001', 'D001', periods=6)
        assert len(history) == 2
        assert history[0]['period'] == '2025-01'
        assert history[0]['status'] == 'adopted'
        assert history[0]['adopted_price'] == 41.04

    @pytest.mark.asyncio
    async def test_empty_history(self):
        db = _make_db([[]])
        history = await get_pricing_history(db, 'S001', 'D999')
        assert history == []
