"""菜单排名引擎测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.menu_ranker import (
    DishScore,
    calc_low_refund_score,
    calc_margin_score,
    calc_stock_score,
    calc_time_slot_score,
    calc_trend_score,
    compute_ranking,
)

SAMPLE_DISHES = [
    {"id": "d1", "name": "剁椒鱼头", "price_fen": 8800, "cost_fen": 3500, "recent_sales": 50, "prev_sales": 30,
     "current_stock": 20, "min_stock": 5, "refund_rate": 0.02, "lunch_sales_pct": 0.6, "dinner_sales_pct": 0.3},
    {"id": "d2", "name": "小炒肉", "price_fen": 4200, "cost_fen": 1800, "recent_sales": 80, "prev_sales": 80,
     "current_stock": 30, "min_stock": 10, "refund_rate": 0.01, "lunch_sales_pct": 0.5, "dinner_sales_pct": 0.4},
    {"id": "d3", "name": "凉拌黄瓜", "price_fen": 900, "cost_fen": 200, "recent_sales": 20, "prev_sales": 40,
     "current_stock": 2, "min_stock": 5, "refund_rate": 0.08, "lunch_sales_pct": 0.3, "dinner_sales_pct": 0.2},
]


class TestTrendScore:
    def test_growth(self):
        assert calc_trend_score(60, 30) > 0.5

    def test_decline(self):
        assert calc_trend_score(20, 40) < 0.5

    def test_stable(self):
        assert calc_trend_score(50, 50) == 0.5

    def test_no_history(self):
        assert calc_trend_score(10, 0) == 0.5

    def test_capped_at_1(self):
        assert calc_trend_score(1000, 1) <= 1.0


class TestMarginScore:
    def test_high_margin(self):
        assert calc_margin_score(10000, 3000) == 0.7

    def test_zero_margin(self):
        assert calc_margin_score(5000, 5000) == 0.0

    def test_negative_price(self):
        assert calc_margin_score(0, 1000) == 0.3


class TestStockScore:
    def test_abundant(self):
        assert calc_stock_score(30, 5) == 1.0

    def test_critical(self):
        assert calc_stock_score(2, 5) < 0.5

    def test_zero_stock(self):
        assert calc_stock_score(0, 5) == 0.0

    def test_zero_min(self):
        assert calc_stock_score(10, 0) == 0.5


class TestTimeSlotScore:
    def test_lunch(self):
        score = calc_time_slot_score({"lunch_sales_pct": 0.7}, "lunch")
        assert score == 0.7

    def test_unknown_slot(self):
        assert calc_time_slot_score({}, "midnight") == 0.3


class TestRefundScore:
    def test_zero_refund(self):
        assert calc_low_refund_score(0) == 1.0

    def test_high_refund(self):
        assert calc_low_refund_score(0.1) == 0.0

    def test_moderate(self):
        assert 0 < calc_low_refund_score(0.05) < 1


class TestDishScore:
    def test_total_weighted(self):
        ds = DishScore(dish_id="x", dish_name="test", trend=1.0, margin=1.0, stock=1.0, time_slot=1.0, low_refund=1.0)
        assert ds.total == 1.0

    def test_highlight_trend(self):
        ds = DishScore(dish_id="x", dish_name="test", trend=0.9)
        assert ds.highlight == "销量持续上升"

    def test_no_highlight(self):
        ds = DishScore(dish_id="x", dish_name="test", trend=0.3, margin=0.3)
        assert ds.highlight is None


class TestComputeRanking:
    def test_returns_ranked_list(self):
        result = compute_ranking(SAMPLE_DISHES, time_slot="lunch", limit=10)
        assert len(result) == 3
        assert result[0]["rank"] == 1
        assert result[0]["total_score"] >= result[1]["total_score"]

    def test_limit(self):
        result = compute_ranking(SAMPLE_DISHES, limit=2)
        assert len(result) == 2

    def test_high_margin_dish_ranks_well(self):
        """高毛利+高趋势的鱼头应排名靠前"""
        result = compute_ranking(SAMPLE_DISHES, time_slot="lunch")
        names = [r["dish_name"] for r in result]
        # 鱼头：高趋势(50>30) + 高毛利(60%) + 高库存 → 应排前2
        assert "剁椒鱼头" in names[:2]

    def test_low_stock_penalized(self):
        """低库存的黄瓜应排名靠后"""
        result = compute_ranking(SAMPLE_DISHES, time_slot="lunch")
        assert result[-1]["dish_name"] == "凉拌黄瓜"

    def test_empty_dishes(self):
        assert compute_ranking([], limit=10) == []
