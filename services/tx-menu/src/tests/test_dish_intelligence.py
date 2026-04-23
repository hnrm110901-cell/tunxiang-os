"""菜品深度智能服务测试 -- 口碑 / 状态推导 / 生命周期 / 动作建议"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dish_intelligence import (
    DishAction,
    DishLifecycle,
    DishStatus,
    _clear_store,
    auto_derive_status,
    calculate_dish_reputation,
    get_dish_lifecycle,
    inject_dish_reviews,
    inject_dish_sales,
    suggest_dish_action,
)

TENANT = "tenant-test-001"


class TestCalculateDishReputation:
    def setup_method(self):
        _clear_store()

    def test_no_reviews_returns_no_data(self):
        result = calculate_dish_reputation("dish-001", TENANT)
        assert result["reputation_level"] == "no_data"
        assert result["total_reviews"] == 0
        assert result["avg_score"] == 0.0

    def test_excellent_reputation(self):
        inject_dish_reviews(
            "dish-002",
            TENANT,
            {
                "total_reviews": 100,
                "positive_count": 95,
                "negative_count": 2,
                "neutral_count": 3,
                "avg_score": 4.7,
                "recommend_count": 80,
                "reorder_count": 40,
                "unique_customers": 90,
            },
        )
        result = calculate_dish_reputation("dish-002", TENANT)
        assert result["reputation_level"] == "excellent"
        assert result["avg_score"] == 4.7
        assert result["negative_rate"] < 0.05

    def test_poor_reputation(self):
        inject_dish_reviews(
            "dish-003",
            TENANT,
            {
                "total_reviews": 50,
                "positive_count": 10,
                "negative_count": 30,
                "neutral_count": 10,
                "avg_score": 2.1,
                "recommend_count": 5,
                "reorder_count": 3,
                "unique_customers": 40,
            },
        )
        result = calculate_dish_reputation("dish-003", TENANT)
        assert result["reputation_level"] == "poor"
        assert result["negative_rate"] > 0.10

    def test_reorder_rate_calculation(self):
        inject_dish_reviews(
            "dish-004",
            TENANT,
            {
                "total_reviews": 80,
                "positive_count": 60,
                "negative_count": 5,
                "neutral_count": 15,
                "avg_score": 4.0,
                "recommend_count": 40,
                "reorder_count": 30,
                "unique_customers": 60,
            },
        )
        result = calculate_dish_reputation("dish-004", TENANT)
        assert result["reorder_rate"] == round(30 / 60, 4)
        assert result["recommend_rate"] == round(40 / 60, 4)

    def test_tenant_id_required(self):
        try:
            calculate_dish_reputation("dish-001", "")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


class TestAutoDeriveStatus:
    def setup_method(self):
        _clear_store()

    def test_no_data_returns_new(self):
        result = auto_derive_status("dish-new", TENANT)
        assert result["status"] == DishStatus.new.value

    def test_new_dish_within_30_days(self):
        inject_dish_sales(
            "dish-n",
            TENANT,
            {
                "total_sales": 50,
                "total_revenue_fen": 500000,
                "cost_fen": 1500,
                "price_fen": 3000,
                "recent_week_sales": 30,
                "previous_week_sales": 20,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "season": None,
                "is_seasonal": False,
            },
        )
        result = auto_derive_status("dish-n", TENANT)
        assert result["status"] == DishStatus.new.value

    def test_star_dish(self):
        # 注入多道菜以支撑百分位计算
        for i in range(10):
            inject_dish_sales(
                f"dish-filler-{i}",
                TENANT,
                {
                    "total_sales": (i + 1) * 10,
                    "total_revenue_fen": 100000,
                    "cost_fen": 2000,
                    "price_fen": 3000,
                    "recent_week_sales": 10,
                    "previous_week_sales": 10,
                    "created_at": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
                    "season": None,
                    "is_seasonal": False,
                },
            )
        # 明星菜：高销高利
        inject_dish_sales(
            "dish-star",
            TENANT,
            {
                "total_sales": 500,
                "total_revenue_fen": 5000000,
                "cost_fen": 1000,
                "price_fen": 5000,
                "recent_week_sales": 50,
                "previous_week_sales": 48,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
                "season": None,
                "is_seasonal": False,
            },
        )
        result = auto_derive_status("dish-star", TENANT)
        assert result["status"] == DishStatus.star.value

    def test_declining_dish(self):
        inject_dish_sales(
            "dish-dec",
            TENANT,
            {
                "total_sales": 100,
                "total_revenue_fen": 300000,
                "cost_fen": 1500,
                "price_fen": 3000,
                "recent_week_sales": 5,
                "previous_week_sales": 20,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "season": None,
                "is_seasonal": False,
            },
        )
        result = auto_derive_status("dish-dec", TENANT)
        assert result["status"] == DishStatus.declining.value
        assert result["metrics"]["growth_rate"] < 0

    def test_seasonal_peak(self):
        inject_dish_sales(
            "dish-season",
            TENANT,
            {
                "total_sales": 200,
                "total_revenue_fen": 600000,
                "cost_fen": 1500,
                "price_fen": 3000,
                "recent_week_sales": 30,
                "previous_week_sales": 25,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "season": "summer",
                "is_seasonal": True,
            },
        )
        result = auto_derive_status("dish-season", TENANT)
        assert result["status"] == DishStatus.seasonal_peak.value


class TestGetDishLifecycle:
    def setup_method(self):
        _clear_store()

    def test_no_data_returns_launch(self):
        result = get_dish_lifecycle("dish-x", TENANT)
        assert result["lifecycle"] == DishLifecycle.launch.value

    def test_launch_phase(self):
        inject_dish_sales(
            "dish-l",
            TENANT,
            {
                "total_sales": 20,
                "recent_week_sales": 15,
                "previous_week_sales": 5,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(),
                "cost_fen": 1000,
                "price_fen": 3000,
            },
        )
        result = get_dish_lifecycle("dish-l", TENANT)
        assert result["lifecycle"] in (DishLifecycle.launch.value, DishLifecycle.growth.value)
        assert result["weeks_since_launch"] == 2

    def test_mature_phase(self):
        inject_dish_sales(
            "dish-m",
            TENANT,
            {
                "total_sales": 1000,
                "recent_week_sales": 50,
                "previous_week_sales": 52,
                "created_at": (datetime.now(timezone.utc) - timedelta(weeks=16)).isoformat(),
                "cost_fen": 1000,
                "price_fen": 3000,
            },
        )
        result = get_dish_lifecycle("dish-m", TENANT)
        assert result["lifecycle"] == DishLifecycle.mature.value
        assert result["health_score"] >= 80.0

    def test_decline_phase(self):
        inject_dish_sales(
            "dish-d",
            TENANT,
            {
                "total_sales": 500,
                "recent_week_sales": 5,
                "previous_week_sales": 30,
                "created_at": (datetime.now(timezone.utc) - timedelta(weeks=30)).isoformat(),
                "cost_fen": 1000,
                "price_fen": 3000,
            },
        )
        result = get_dish_lifecycle("dish-d", TENANT)
        assert result["lifecycle"] == DishLifecycle.decline.value
        assert result["health_score"] <= 40.0

    def test_weeks_calculation(self):
        inject_dish_sales(
            "dish-w",
            TENANT,
            {
                "total_sales": 100,
                "recent_week_sales": 10,
                "previous_week_sales": 10,
                "created_at": (datetime.now(timezone.utc) - timedelta(weeks=7)).isoformat(),
                "cost_fen": 1000,
                "price_fen": 3000,
            },
        )
        result = get_dish_lifecycle("dish-w", TENANT)
        assert result["weeks_since_launch"] == 7


class TestSuggestDishAction:
    def setup_method(self):
        _clear_store()

    def test_new_dish_suggest_observe(self):
        inject_dish_sales(
            "dish-new",
            TENANT,
            {
                "total_sales": 10,
                "total_revenue_fen": 100000,
                "cost_fen": 1000,
                "price_fen": 3000,
                "recent_week_sales": 10,
                "previous_week_sales": 0,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
                "season": None,
                "is_seasonal": False,
            },
        )
        result = suggest_dish_action("dish-new", TENANT)
        assert result["action"] == DishAction.observe.value
        assert result["priority"] == "low"

    def test_declining_suggest_lower_price(self):
        inject_dish_sales(
            "dish-dc",
            TENANT,
            {
                "total_sales": 100,
                "total_revenue_fen": 300000,
                "cost_fen": 1500,
                "price_fen": 3000,
                "recent_week_sales": 5,
                "previous_week_sales": 20,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "season": None,
                "is_seasonal": False,
            },
        )
        result = suggest_dish_action("dish-dc", TENANT)
        assert result["action"] in (DishAction.lower_price.value, DishAction.replace.value)

    def test_result_includes_derived_data(self):
        result = suggest_dish_action("dish-nodata", TENANT)
        assert "derived_status" in result
        assert "lifecycle" in result
        assert "reputation" in result

    def test_seasonal_suggest_promote(self):
        inject_dish_sales(
            "dish-sp",
            TENANT,
            {
                "total_sales": 200,
                "total_revenue_fen": 600000,
                "cost_fen": 1500,
                "price_fen": 3000,
                "recent_week_sales": 30,
                "previous_week_sales": 25,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "season": "winter",
                "is_seasonal": True,
            },
        )
        result = suggest_dish_action("dish-sp", TENANT)
        assert result["action"] == DishAction.promote.value
        assert result["priority"] == "high"

    def test_tenant_id_required(self):
        try:
            suggest_dish_action("dish-001", "")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass
