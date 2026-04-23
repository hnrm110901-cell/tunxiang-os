"""门店健康指数纯函数测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.store_health_service import (
    classify_health,
    compute_health_score,
    find_weakest_dimension,
    score_complaint_rate,
    score_cost_rate,
    score_revenue_completion,
    score_staff_efficiency,
    score_table_turnover,
)


class TestComputeHealthScore:
    def test_all_dimensions(self):
        scores = {
            "revenue_completion": 90,
            "table_turnover": 80,
            "cost_rate": 70,
            "complaint_rate": 85,
            "staff_efficiency": 75,
        }
        result = compute_health_score(scores)
        # 加权：90*0.3 + 80*0.2 + 70*0.25 + 85*0.15 + 75*0.1 = 27+16+17.5+12.75+7.5 = 80.75
        assert result == 80.8  # rounded

    def test_missing_dimension_renormalized(self):
        scores = {"revenue_completion": 100, "table_turnover": None, "cost_rate": 100}
        result = compute_health_score(scores)
        # 只有 revenue(0.3) + cost(0.25)，weight=0.55，score=100
        assert result == 100.0

    def test_all_none_returns_50(self):
        assert compute_health_score({"a": None, "b": None}) == 50.0

    def test_empty_returns_50(self):
        assert compute_health_score({}) == 50.0


class TestClassifyHealth:
    def test_excellent(self):
        assert classify_health(90) == "excellent"

    def test_good(self):
        assert classify_health(75) == "good"

    def test_warning(self):
        assert classify_health(55) == "warning"

    def test_critical(self):
        assert classify_health(30) == "critical"

    def test_boundary_85(self):
        assert classify_health(85) == "excellent"

    def test_boundary_70(self):
        assert classify_health(70) == "good"

    def test_boundary_50(self):
        assert classify_health(50) == "warning"


class TestDimensionScores:
    def test_revenue_completion(self):
        # 月目标 10万元，当日营收 3500元(350000分)，月30天，日均目标 333333分
        score = score_revenue_completion(350000, 100000, 30)
        assert score is not None
        assert score + 5 >= 100  # ~105 capped at 100

    def test_revenue_no_target(self):
        assert score_revenue_completion(100000, 0, 30) is None

    def test_table_turnover(self):
        score = score_table_turnover(80, 50)  # 1.6翻台率 / 2.0目标 = 80分
        assert score == 80.0

    def test_table_no_seats(self):
        assert score_table_turnover(10, 0) is None

    def test_cost_rate_ok(self):
        assert score_cost_rate("ok") == 100.0

    def test_cost_rate_warning(self):
        assert score_cost_rate("warning") == 60.0

    def test_cost_rate_critical(self):
        assert score_cost_rate("critical") == 20.0

    def test_cost_rate_none(self):
        assert score_cost_rate(None) is None

    def test_complaint_rate_zero(self):
        assert score_complaint_rate(0, 100) == 100.0

    def test_complaint_rate_half(self):
        assert score_complaint_rate(50, 100) == 0.0

    def test_complaint_no_orders(self):
        assert score_complaint_rate(0, 0) is None

    def test_staff_efficiency(self):
        score = score_staff_efficiency(10000, 25)  # 400元/人 / 500目标 = 80分
        assert score == 80.0

    def test_staff_no_staff(self):
        assert score_staff_efficiency(10000, 0) is None

    def test_find_weakest(self):
        scores = {"revenue_completion": 90, "cost_rate": 40, "staff_efficiency": 70}
        assert find_weakest_dimension(scores) == "cost_rate"
