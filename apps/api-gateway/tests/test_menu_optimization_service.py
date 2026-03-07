"""Tests for menu_optimization_service.py — Phase 6 Month 2"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys

mock_settings = MagicMock()
mock_settings.database_url = "postgresql+asyncpg://x:x@localhost/x"
mock_config_mod = MagicMock()
mock_config_mod.settings = mock_settings
sys.modules.setdefault("src.core.config", mock_config_mod)

from src.services.menu_optimization_service import (  # noqa: E402
    compute_price_increase_impact,
    compute_cost_reduction_impact,
    compute_promote_impact,
    compute_discontinue_impact,
    compute_bundle_impact,
    compute_priority_score,
    classify_urgency,
    generate_rec_description,
    build_dish_recommendations,
    summarize_recommendations,
    generate_menu_recommendations,
    get_menu_recommendations,
    get_recommendation_summary,
    update_recommendation_status,
    get_dish_recommendations,
    REC_TYPES, REC_LABELS, REC_TITLES,
    PRICE_INCREASE_LIFT_PCT, PRICE_DEMAND_RETENTION,
    COST_REDUCTION_TARGET_FCR, COST_REDUCTION_FCR_THRESHOLD,
    DISCONTINUE_MAX_ORDERS, DISCONTINUE_MAX_GPM,
)


# ══════════════════════════════════════════════════════════════════════════════
# compute_price_increase_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputePriceIncreaseImpact:
    def test_normal(self):
        imp = compute_price_increase_impact(100.0, 50)
        # new_price = 107, new_orders = 50 * 0.92 = 46
        # revenue_delta = 107*46 - 100*50 = 4922 - 5000 = -78
        # profit_delta  = 100 * 0.07 * 46 = 322
        assert abs(imp["revenue_delta"] - (-78.0)) < 0.1
        assert abs(imp["profit_delta"]  - 322.0)   < 0.1
        assert abs(imp["new_price"]     - 107.0)   < 0.1

    def test_zero_price(self):
        imp = compute_price_increase_impact(0.0, 50)
        assert imp["profit_delta"] == 0.0

    def test_zero_orders(self):
        imp = compute_price_increase_impact(100.0, 0)
        assert imp["profit_delta"] == 0.0

    def test_full_retention(self):
        # demand_retention=1.0 → no lost orders
        imp = compute_price_increase_impact(100.0, 100, lift_pct=10.0, demand_retention=1.0)
        # revenue_delta = 110*100 - 100*100 = 1000
        # profit_delta  = 100 * 0.10 * 100 = 1000
        assert abs(imp["revenue_delta"] - 1000.0) < 0.1
        assert abs(imp["profit_delta"]  - 1000.0) < 0.1

    def test_profit_always_positive(self):
        # profit_delta should always be >= 0 when price > 0 and orders > 0
        imp = compute_price_increase_impact(50.0, 30, lift_pct=5.0, demand_retention=0.80)
        assert imp["profit_delta"] >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_cost_reduction_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeCostReductionImpact:
    def test_normal(self):
        # revenue=10000, current_fcr=40%, target=35% → saving = 5%*10000 = 500
        imp = compute_cost_reduction_impact(10000.0, 40.0)
        assert abs(imp["cost_saving"]  - 500.0) < 0.1
        assert abs(imp["profit_delta"] - 500.0) < 0.1

    def test_already_at_target(self):
        imp = compute_cost_reduction_impact(10000.0, COST_REDUCTION_TARGET_FCR)
        assert imp["profit_delta"] == 0.0

    def test_below_target(self):
        imp = compute_cost_reduction_impact(10000.0, 30.0)
        assert imp["profit_delta"] == 0.0

    def test_zero_revenue(self):
        imp = compute_cost_reduction_impact(0.0, 45.0)
        assert imp["profit_delta"] == 0.0

    def test_custom_target(self):
        imp = compute_cost_reduction_impact(5000.0, 50.0, target_fcr=40.0)
        # (50-40)/100 * 5000 = 500
        assert abs(imp["profit_delta"] - 500.0) < 0.1


# ══════════════════════════════════════════════════════════════════════════════
# compute_promote_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputePromoteImpact:
    def test_normal(self):
        # count=20, price=60, gpm=70%, lift=30%
        # extra_orders = 6, revenue_delta = 360, profit_delta = 252
        imp = compute_promote_impact(20, 60.0, 70.0)
        assert imp["order_delta"]   == 6
        assert abs(imp["revenue_delta"] - 360.0) < 0.1
        assert abs(imp["profit_delta"]  - 252.0) < 0.1

    def test_zero_orders(self):
        imp = compute_promote_impact(0, 60.0, 70.0)
        assert imp["profit_delta"] == 0.0

    def test_zero_price(self):
        imp = compute_promote_impact(20, 0.0, 70.0)
        assert imp["profit_delta"] == 0.0

    def test_zero_margin(self):
        imp = compute_promote_impact(20, 60.0, 0.0)
        assert imp["profit_delta"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_discontinue_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeDiscontinueImpact:
    def test_small_profit_dish(self):
        # kitchen_savings=300, lost_profit=100 → net=200
        imp = compute_discontinue_impact(500.0, 100.0)
        assert abs(imp["profit_delta"]    - 200.0) < 0.1
        assert imp["kitchen_savings"]     == 300.0
        assert abs(imp["lost_profit"]     - 100.0) < 0.1

    def test_negative_gross_profit(self):
        # lost_profit = max(0, -50) = 0 → net = 300
        imp = compute_discontinue_impact(500.0, -50.0)
        assert abs(imp["profit_delta"] - 300.0) < 0.1

    def test_high_profit_dish_negative_net(self):
        # kitchen_savings=300, lost_profit=2000 → net=-1700
        imp = compute_discontinue_impact(5000.0, 2000.0)
        assert imp["profit_delta"] < 0.0

    def test_zero_profit_dish(self):
        imp = compute_discontinue_impact(500.0, 0.0)
        assert abs(imp["profit_delta"] - 300.0) < 0.1


# ══════════════════════════════════════════════════════════════════════════════
# compute_bundle_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeBundleImpact:
    def test_smaller_than_promote(self):
        # bundle_lift < promote_lift → bundle profit < promote profit
        promo  = compute_promote_impact(10, 50.0, 60.0)
        bundle = compute_bundle_impact(10, 50.0, 60.0)
        assert bundle["profit_delta"] < promo["profit_delta"]

    def test_zero_orders(self):
        imp = compute_bundle_impact(0, 50.0, 60.0)
        assert imp["profit_delta"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# compute_priority_score
# ══════════════════════════════════════════════════════════════════════════════

class TestComputePriorityScore:
    def test_high_impact_high_conf(self):
        # impact_score = min(50, 50000/500) = 50
        # conf_score   = min(50, 90*0.5)   = 45
        # total = 95
        score = compute_priority_score("price_increase", 50000.0, 90.0)
        assert abs(score - 95.0) < 0.1

    def test_zero_impact(self):
        # impact=0, conf=80 → 0 + 40 = 40
        score = compute_priority_score("promote", 0.0, 80.0)
        assert abs(score - 40.0) < 0.1

    def test_caps_at_100(self):
        score = compute_priority_score("discontinue", 1_000_000.0, 100.0)
        assert score == 100.0

    def test_low_priority(self):
        # impact=50 → score=0.1, conf=10 → score=5 → total≈5.1
        score = compute_priority_score("bundle", 50.0, 10.0)
        assert score < 10.0

    def test_negative_impact_uses_abs(self):
        # discontinue revenue_impact can be negative
        score_pos = compute_priority_score("discontinue", 5000.0, 70.0)
        score_neg = compute_priority_score("discontinue", -5000.0, 70.0)
        assert abs(score_pos - score_neg) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# classify_urgency
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyUrgency:
    def test_high(self):
        assert classify_urgency(75.0)  == "high"

    def test_boundary_70_is_high(self):
        assert classify_urgency(70.0)  == "high"

    def test_medium(self):
        assert classify_urgency(50.0)  == "medium"

    def test_boundary_30_is_medium(self):
        assert classify_urgency(30.0)  == "medium"

    def test_just_below_30_is_low(self):
        assert classify_urgency(29.9)  == "low"

    def test_zero_is_low(self):
        assert classify_urgency(0.0)   == "low"


# ══════════════════════════════════════════════════════════════════════════════
# generate_rec_description
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateRecDescription:
    def test_contains_dish_name(self):
        desc = generate_rec_description("price_increase", "红烧肉", 300.0, 35.0, 65.0, 150)
        assert "红烧肉" in desc

    def test_max_200_chars(self):
        for rt in REC_TYPES:
            desc = generate_rec_description(rt, "非常非常长的菜品名称" * 5, 999.0, 42.0, 58.0, 10)
            assert len(desc) <= 200

    def test_all_types_return_string(self):
        for rt in REC_TYPES:
            desc = generate_rec_description(rt, "测试菜", 100.0, 38.0, 62.0, 30)
            assert isinstance(desc, str)
            assert len(desc) > 0


# ══════════════════════════════════════════════════════════════════════════════
# build_dish_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildDishRecommendations:
    # Star: gpm=65≥60 → price_increase; fcr=35≤38 → no cost_reduction
    STAR = {
        "dish_id": "D001", "dish_name": "红烧肉", "category": "热菜",
        "bcg_quadrant": "star", "order_count": 150,
        "avg_selling_price": 50.0, "revenue_yuan": 7500.0,
        "food_cost_yuan": 2625.0, "food_cost_rate": 35.0,
        "gross_profit_yuan": 4875.0, "gross_profit_margin": 65.0,
    }
    # Cash cow: fcr=48>38 → cost_reduction; gpm=52≥40 → price_increase
    CASH_COW = {
        "dish_id": "D002", "dish_name": "炸鸡腿", "category": "热菜",
        "bcg_quadrant": "cash_cow", "order_count": 200,
        "avg_selling_price": 30.0, "revenue_yuan": 6000.0,
        "food_cost_yuan": 2880.0, "food_cost_rate": 48.0,
        "gross_profit_yuan": 3120.0, "gross_profit_margin": 52.0,
    }
    # Question mark: → promote + bundle
    QUESTION_MARK = {
        "dish_id": "D003", "dish_name": "松露炒蛋", "category": "热菜",
        "bcg_quadrant": "question_mark", "order_count": 10,
        "avg_selling_price": 80.0, "revenue_yuan": 800.0,
        "food_cost_yuan": 240.0, "food_cost_rate": 30.0,
        "gross_profit_yuan": 560.0, "gross_profit_margin": 70.0,
    }
    # Dog (cost_reduction path): fcr=65>38, gpm=35>30 OR cnt>15 → cost_reduction
    DOG_COST = {
        "dish_id": "D004", "dish_name": "老菜甲", "category": "素菜",
        "bcg_quadrant": "dog", "order_count": 20,       # cnt>15 → skip discontinue check
        "avg_selling_price": 20.0, "revenue_yuan": 400.0,
        "food_cost_yuan": 260.0, "food_cost_rate": 65.0,
        "gross_profit_yuan": 140.0, "gross_profit_margin": 35.0,
    }
    # Dog (discontinue path): cnt≤15 AND gpm≤30
    DOG_DISC = {
        "dish_id": "D005", "dish_name": "老菜乙", "category": "素菜",
        "bcg_quadrant": "dog", "order_count": 5,
        "avg_selling_price": 20.0, "revenue_yuan": 100.0,
        "food_cost_yuan": 80.0, "food_cost_rate": 80.0,
        "gross_profit_yuan": 20.0, "gross_profit_margin": 20.0,
    }

    def test_star_gets_price_increase(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.STAR)]
        assert "price_increase" in types

    def test_star_no_cost_reduction_when_fcr_low(self):
        # fcr=35 ≤ threshold=38 → no cost_reduction
        types = [r["rec_type"] for r in build_dish_recommendations(self.STAR)]
        assert "cost_reduction" not in types

    def test_cash_cow_gets_cost_reduction(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.CASH_COW)]
        assert "cost_reduction" in types

    def test_cash_cow_gets_price_increase(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.CASH_COW)]
        assert "price_increase" in types

    def test_question_mark_gets_promote(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.QUESTION_MARK)]
        assert "promote" in types

    def test_question_mark_gets_bundle(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.QUESTION_MARK)]
        assert "bundle" in types

    def test_dog_discontinue_path(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.DOG_DISC)]
        assert "discontinue" in types

    def test_dog_cost_reduction_path(self):
        types = [r["rec_type"] for r in build_dish_recommendations(self.DOG_COST)]
        assert "cost_reduction" in types

    def test_at_most_2_recs(self):
        for dish in [self.STAR, self.CASH_COW, self.QUESTION_MARK, self.DOG_COST, self.DOG_DISC]:
            assert len(build_dish_recommendations(dish)) <= 2

    def test_sorted_by_priority_desc(self):
        recs = build_dish_recommendations(self.CASH_COW)
        if len(recs) > 1:
            assert recs[0]["priority_score"] >= recs[1]["priority_score"]

    def test_required_fields(self):
        recs = build_dish_recommendations(self.STAR)
        assert len(recs) > 0
        required = ["rec_type", "title", "action", "description",
                    "expected_profit_impact_yuan", "confidence_pct",
                    "priority_score", "urgency"]
        for field in required:
            assert field in recs[0], f"Missing: {field}"

    def test_description_within_200(self):
        for dish in [self.STAR, self.CASH_COW, self.QUESTION_MARK, self.DOG_DISC]:
            for rec in build_dish_recommendations(dish):
                assert len(rec["description"]) <= 200

    def test_profit_impact_positive_for_star(self):
        # price_increase for star should have positive profit_delta
        recs = build_dish_recommendations(self.STAR)
        pi = next(r for r in recs if r["rec_type"] == "price_increase")
        assert pi["expected_profit_impact_yuan"] > 0

    def test_empty_dish(self):
        # No crash on minimal input
        recs = build_dish_recommendations({"bcg_quadrant": "dog"})
        assert isinstance(recs, list)


# ══════════════════════════════════════════════════════════════════════════════
# summarize_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizeRecommendations:
    RECORDS = [
        {"rec_type": "price_increase", "expected_profit_impact_yuan": 500.0, "status": "pending"},
        {"rec_type": "cost_reduction", "expected_profit_impact_yuan": 800.0, "status": "adopted"},
        {"rec_type": "promote",        "expected_profit_impact_yuan": 300.0, "status": "pending"},
        {"rec_type": "discontinue",    "expected_profit_impact_yuan": 200.0, "status": "dismissed"},
        {"rec_type": "bundle",         "expected_profit_impact_yuan": 150.0, "status": "pending"},
    ]

    def test_total_count(self):
        s = summarize_recommendations(self.RECORDS)
        assert s["total_count"] == 5

    def test_pending_count(self):
        s = summarize_recommendations(self.RECORDS)
        assert s["pending_count"] == 3

    def test_adopted_count(self):
        s = summarize_recommendations(self.RECORDS)
        assert s["adopted_count"] == 1

    def test_total_profit_impact(self):
        s = summarize_recommendations(self.RECORDS)
        expected = 500.0 + 800.0 + 300.0 + 200.0 + 150.0
        assert abs(s["total_profit_impact_yuan"] - expected) < 0.1

    def test_all_rec_types_present(self):
        s = summarize_recommendations(self.RECORDS)
        types = {item["rec_type"] for item in s["by_type"]}
        assert types == set(REC_TYPES)

    def test_empty_input(self):
        s = summarize_recommendations([])
        assert s["total_count"] == 0
        assert s["pending_count"] == 0
        assert abs(s["total_profit_impact_yuan"]) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# DB 层
# ══════════════════════════════════════════════════════════════════════════════

def _make_db(calls: list):
    call_idx = [0]

    async def mock_execute(stmt, params=None):
        idx = call_idx[0]
        call_idx[0] += 1
        val = calls[idx] if idx < len(calls) else []
        r = MagicMock()
        if val is None or val == []:
            r.fetchone.return_value = None
            r.fetchall.return_value = []
        elif isinstance(val, list):
            r.fetchall.return_value = val
            r.fetchone.return_value = val[0] if val else None
        else:
            r.fetchone.return_value = val
            r.fetchall.return_value = [val]
        return r

    db = MagicMock()
    db.execute = mock_execute
    db.commit   = AsyncMock()
    return db


class TestGenerateMenuRecommendations:
    @pytest.mark.asyncio
    async def test_no_bcg_data(self):
        db = _make_db([[]])
        result = await generate_menu_recommendations(db, "S001", "2024-07")
        assert result["rec_count"]  == 0
        assert result["dish_count"] == 0

    @pytest.mark.asyncio
    async def test_star_dish_one_rec(self):
        # Star, gpm=65≥60 → price_increase (1 rec)
        # fcr=35≤38 → no cost_reduction
        raw = [("D001", "红烧肉", "热菜", "star",
                150, 50.0, 7500.0, 2625.0, 35.0, 4875.0, 65.0, 100.0, 100.0)]
        # calls: 1 fetch + 1 upsert
        db = _make_db([raw, None])
        result = await generate_menu_recommendations(db, "S001", "2024-07")
        assert result["dish_count"] == 1
        assert result["rec_count"]  == 1

    @pytest.mark.asyncio
    async def test_question_mark_dish_two_recs(self):
        # question_mark always gets promote + bundle = 2 recs
        raw = [("D003", "松露炒蛋", "热菜", "question_mark",
                10, 80.0, 800.0, 240.0, 30.0, 560.0, 70.0, 20.0, 90.0)]
        # calls: 1 fetch + 2 upserts
        db = _make_db([raw, None, None])
        result = await generate_menu_recommendations(db, "S001", "2024-07")
        assert result["dish_count"] == 1
        assert result["rec_count"]  == 2

    @pytest.mark.asyncio
    async def test_commit_called(self):
        db = _make_db([[]])
        await generate_menu_recommendations(db, "S001", "2024-07")
        # Even with no data, no commit needed (returns early)
        assert db.commit.call_count == 0


class TestGetMenuRecommendations:
    # 23 columns: id, dish_id, dish_name, category, bcg_quadrant,
    #   rec_type, title, description, action,
    #   rev_impact, cost_impact, profit_impact,
    #   confidence, priority, urgency,
    #   fcr, gpm, cnt, price, revenue, profit,
    #   status, computed_at
    ROW = (
        1, "D001", "红烧肉", "热菜", "star",
        "price_increase", "明星菜品具备提价空间", "desc", "action",
        322.0, 0.0, 322.0,
        75.0, 62.5, "medium",
        35.0, 65.0, 150, 50.0, 7500.0, 4875.0,
        "pending", None,
    )

    @pytest.mark.asyncio
    async def test_returns_list(self):
        db = _make_db([[self.ROW]])
        recs = await get_menu_recommendations(db, "S001", "2024-07")
        assert len(recs) == 1
        assert recs[0]["rec_type"]  == "price_increase"
        assert recs[0]["rec_label"] == "提价空间"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        recs = await get_menu_recommendations(db, "S001", "2024-07")
        assert recs == []

    @pytest.mark.asyncio
    async def test_with_rec_type_filter(self):
        db = _make_db([[self.ROW]])
        recs = await get_menu_recommendations(db, "S001", "2024-07", rec_type="price_increase")
        assert len(recs) == 1

    @pytest.mark.asyncio
    async def test_with_status_filter(self):
        db = _make_db([[self.ROW]])
        recs = await get_menu_recommendations(db, "S001", "2024-07", status="pending")
        assert len(recs) == 1

    @pytest.mark.asyncio
    async def test_with_both_filters(self):
        db = _make_db([[self.ROW]])
        recs = await get_menu_recommendations(
            db, "S001", "2024-07", rec_type="price_increase", status="pending"
        )
        assert len(recs) == 1


class TestGetRecommendationSummary:
    @pytest.mark.asyncio
    async def test_aggregates_correctly(self):
        rows = [
            ("price_increase", "pending",  3, 900.0),
            ("cost_reduction", "adopted",  2, 600.0),
            ("promote",        "pending",  1, 300.0),
        ]
        db = _make_db([rows])
        s = await get_recommendation_summary(db, "S001", "2024-07")
        assert s["pending_count"] == 4   # 3 + 1
        assert s["adopted_count"] == 2

    @pytest.mark.asyncio
    async def test_all_types_present(self):
        db = _make_db([[]])
        s = await get_recommendation_summary(db, "S001", "2024-07")
        types = {item["rec_type"] for item in s["by_type"]}
        assert types == set(REC_TYPES)

    @pytest.mark.asyncio
    async def test_pending_impact(self):
        rows = [
            ("price_increase", "pending",  2, 400.0),
            ("cost_reduction", "adopted",  1, 200.0),
        ]
        db = _make_db([rows])
        s = await get_recommendation_summary(db, "S001", "2024-07")
        # Only pending impact counted
        assert abs(s["total_pending_profit_impact_yuan"] - 400.0) < 0.1


class TestUpdateRecommendationStatus:
    @pytest.mark.asyncio
    async def test_adopt(self):
        db = _make_db([(1,)])
        result = await update_recommendation_status(db, 1, "adopted")
        assert result["updated"]    is True
        assert result["new_status"] == "adopted"

    @pytest.mark.asyncio
    async def test_dismiss(self):
        db = _make_db([(1,)])
        result = await update_recommendation_status(db, 1, "dismissed")
        assert result["updated"]    is True
        assert result["new_status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_invalid_status(self):
        db = _make_db([])
        result = await update_recommendation_status(db, 1, "deleted")
        assert result["updated"]  is False
        assert result["reason"]   == "invalid_status"

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = _make_db([None])
        result = await update_recommendation_status(db, 999, "adopted")
        assert result["updated"]  is False
        assert result["reason"]   == "not_found_or_not_pending"

    @pytest.mark.asyncio
    async def test_commit_only_on_success(self):
        db = _make_db([None])
        await update_recommendation_status(db, 999, "adopted")
        assert db.commit.call_count == 0


class TestGetDishRecommendations:
    @pytest.mark.asyncio
    async def test_returns_history(self):
        rows = [
            ("2024-07", "price_increase", "明星菜品具备提价空间", 322.0, 75.0, 62.5, "medium", "pending"),
            ("2024-06", "price_increase", "明星菜品具备提价空间", 300.0, 75.0, 60.0, "medium", "adopted"),
        ]
        db = _make_db([rows])
        history = await get_dish_recommendations(db, "S001", "D001")
        assert len(history)          == 2
        assert history[0]["period"]  == "2024-07"
        assert history[0]["rec_label"] == "提价空间"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        history = await get_dish_recommendations(db, "S001", "D999")
        assert history == []
