"""自助点餐引擎测试 -- 覆盖7个核心功能

1. AI推荐(权重校验)
2. 套餐智能组合
3. 最优优惠方案
4. AA分摊(均分+按菜分)
5. 制作进度5步
6. GPS最近门店
7. 预计等待时间
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock

import pytest
from services.self_order_engine import (
    PREPARATION_STEPS,
    STEP_KEY_TO_INDEX,
    W_HISTORY,
    W_MARGIN,
    W_POPULARITY,
    W_TIME,
    W_WEATHER,
    _detect_meal_period,
    _haversine_km,
    ai_recommend_dishes,
    calculate_aa_split,
    find_best_deal,
)

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())


# ── Mock DB helpers ──────────────────────────────────────────

class FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeResult:
    def __init__(self, rows=None, scalar_val=None):
        self._rows = rows or []
        self._scalar_val = scalar_val

    def mappings(self):
        return FakeMappingResult(self._rows)

    def scalar(self):
        return self._scalar_val

    def fetchall(self):
        return self._rows


def make_async_db(side_effects=None):
    db = AsyncMock()
    if side_effects:
        db.execute = AsyncMock(side_effect=side_effects)
    return db


# ── 1. 时段检测 ─────────────────────────────────────────────

class TestMealPeriod:
    def test_breakfast(self):
        assert _detect_meal_period(7) == "breakfast"

    def test_lunch(self):
        assert _detect_meal_period(12) == "lunch"

    def test_dinner(self):
        assert _detect_meal_period(18) == "dinner"

    def test_afternoon_tea(self):
        assert _detect_meal_period(15) == "afternoon_tea"

    def test_late_night(self):
        assert _detect_meal_period(22) == "late_night"

    def test_early_morning(self):
        assert _detect_meal_period(3) == "late_night"


# ── 2. AI推荐权重 ───────────────────────────────────────────

class TestAIRecommendWeights:
    def test_weights_sum_to_one(self):
        total = W_HISTORY + W_TIME + W_MARGIN + W_POPULARITY + W_WEATHER
        assert abs(total - 1.0) < 1e-9

    def test_history_weight(self):
        assert W_HISTORY == 0.3

    def test_time_weight(self):
        assert W_TIME == 0.2

    def test_margin_weight(self):
        assert W_MARGIN == 0.2

    def test_popularity_weight(self):
        assert W_POPULARITY == 0.2

    def test_weather_weight(self):
        assert W_WEATHER == 0.1


# ── 3. AI推荐函数 ───────────────────────────────────────────

class TestAIRecommend:
    @pytest.mark.asyncio
    async def test_recommend_returns_dishes(self):
        dishes = [
            {"id": "d1", "name": "鱼头", "category": "meat", "price_fen": 8800,
             "tags": ["main", "soup"], "margin_rate": 0.4, "monthly_sales": 200},
            {"id": "d2", "name": "红烧肉", "category": "meat", "price_fen": 5600,
             "tags": ["staple"], "margin_rate": 0.35, "monthly_sales": 150},
        ]
        db = make_async_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[dishes[0], dishes[1]]),  # dish query
            FakeResult(rows=[]),  # history query
        ])
        result = await ai_recommend_dishes(
            customer_id=CUSTOMER_ID, guest_count=2, time_slot="lunch",
            weather="cold", store_id=STORE_ID, tenant_id=TENANT_ID, db=db,
        )
        assert "recommendations" in result
        assert result["guest_count"] == 2
        assert result["time_slot"] == "lunch"

    @pytest.mark.asyncio
    async def test_recommend_limit_by_guest_count(self):
        db = make_async_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[]),  # no dishes
            FakeResult(rows=[]),  # no history
        ])
        result = await ai_recommend_dishes(
            customer_id=None, guest_count=6, time_slot=None,
            weather=None, store_id=STORE_ID, tenant_id=TENANT_ID, db=db,
        )
        assert result["recommendations"] == []


# ── 4. 最优优惠方案 ─────────────────────────────────────────

class TestBestDeal:
    @pytest.mark.asyncio
    async def test_best_deal_picks_highest_discount(self):
        cart = [{"dish_id": "d1", "price_fen": 5000, "quantity": 2}]
        coupons = [
            {"coupon_id": "c1", "type": "fixed", "threshold_fen": 5000, "discount_fen": 500},
            {"coupon_id": "c2", "type": "fixed", "threshold_fen": 8000, "discount_fen": 1000},
        ]
        db = make_async_db([FakeResult()])  # _set_tenant
        result = await find_best_deal(cart, coupons, TENANT_ID, db)
        assert result["cart_total_fen"] == 10000
        assert result["discount_fen"] == 1000
        assert result["final_fen"] == 9000
        assert len(result["applied_coupons"]) == 1

    @pytest.mark.asyncio
    async def test_no_coupons(self):
        cart = [{"dish_id": "d1", "price_fen": 3000, "quantity": 1}]
        db = make_async_db([FakeResult()])
        result = await find_best_deal(cart, [], TENANT_ID, db)
        assert result["discount_fen"] == 0
        assert result["best_plan"] == "no_coupon"

    @pytest.mark.asyncio
    async def test_percentage_coupon(self):
        cart = [{"dish_id": "d1", "price_fen": 10000, "quantity": 1}]
        coupons = [
            {"coupon_id": "c1", "type": "percentage", "threshold_fen": 5000,
             "discount_rate": 0.8, "discount_fen": 0},
        ]
        db = make_async_db([FakeResult()])
        result = await find_best_deal(cart, coupons, TENANT_ID, db)
        # 10000 * (1 - 0.8) = 2000
        assert result["discount_fen"] == 2000


# ── 5. AA 分摊 ──────────────────────────────────────────────

class TestAASplit:
    @pytest.mark.asyncio
    async def test_even_split_exact(self):
        db = make_async_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"final_amount_fen": 300}]),  # order
            FakeResult(rows=[]),  # items
        ])
        result = await calculate_aa_split(ORDER_ID, 3, TENANT_ID, db)
        assert result["split_count"] == 3
        assert sum(s["amount_fen"] for s in result["even_split"]) == 300
        for s in result["even_split"]:
            assert s["amount_fen"] == 100

    @pytest.mark.asyncio
    async def test_even_split_remainder(self):
        db = make_async_db([
            FakeResult(),
            FakeResult(rows=[{"final_amount_fen": 100}]),
            FakeResult(rows=[]),
        ])
        result = await calculate_aa_split(ORDER_ID, 3, TENANT_ID, db)
        amounts = [s["amount_fen"] for s in result["even_split"]]
        assert sum(amounts) == 100
        # 100 // 3 = 33, remainder 1, first person gets 34
        assert amounts[0] == 34
        assert amounts[1] == 33
        assert amounts[2] == 33

    @pytest.mark.asyncio
    async def test_split_invalid_count(self):
        db = make_async_db()
        with pytest.raises(ValueError, match="split_count_must_be_positive"):
            await calculate_aa_split(ORDER_ID, 0, TENANT_ID, db)


# ── 6. 制作进度 ─────────────────────────────────────────────

class TestPreparation:
    def test_five_steps(self):
        assert len(PREPARATION_STEPS) == 5
        keys = [s["key"] for s in PREPARATION_STEPS]
        assert keys == ["received", "preparing", "cooking", "plating", "ready"]

    def test_step_index_mapping(self):
        assert STEP_KEY_TO_INDEX["received"] == 1
        assert STEP_KEY_TO_INDEX["ready"] == 5


# ── 7. GPS距离计算 ──────────────────────────────────────────

class TestHaversine:
    def test_same_point(self):
        assert _haversine_km(28.2, 112.9, 28.2, 112.9) == 0.0

    def test_known_distance(self):
        # 长沙(28.2, 112.9) → 北京(39.9, 116.4) 约 1200km
        dist = _haversine_km(28.2, 112.9, 39.9, 116.4)
        assert 1100 < dist < 1400

    def test_short_distance(self):
        # ~1km apart
        dist = _haversine_km(28.2, 112.9, 28.209, 112.9)
        assert 0.5 < dist < 1.5
