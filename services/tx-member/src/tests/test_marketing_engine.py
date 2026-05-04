"""营销方案引擎测试 — 覆盖 7 种方案 + 互斥 + 执行顺序 + API"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
from services.marketing_engine import (
    apply_schemes_in_order,
    calculate_add_on,
    calculate_buy_gift,
    calculate_member_discount,
    calculate_order_discount,
    calculate_rebuy,
    calculate_special_price,
    calculate_threshold,
    check_exclusion,
)

client = TestClient(app)

# ---------------------------------------------------------------------------
# 公共测试数据
# ---------------------------------------------------------------------------

ITEMS = [
    {"dish_id": "d1", "name": "鱼头", "price_fen": 8800, "quantity": 1},
    {"dish_id": "d2", "name": "红烧肉", "price_fen": 5600, "quantity": 2},
    {"dish_id": "d3", "name": "青菜", "price_fen": 1800, "quantity": 1},
]
# 总价 = 8800 + 5600*2 + 1800 = 21800


# ---------------------------------------------------------------------------
# 1. 特价优惠
# ---------------------------------------------------------------------------


class TestSpecialPrice:
    def test_basic(self):
        rules = {"dish_prices": {"d1": 6800}}
        r = calculate_special_price(ITEMS, rules)
        assert r["discount_fen"] == 2000  # 8800 - 6800
        assert r["applied_schemes"] == ["special_price"]
        assert len(r["details"]) == 1

    def test_no_match(self):
        rules = {"dish_prices": {"d999": 100}}
        r = calculate_special_price(ITEMS, rules)
        assert r["discount_fen"] == 0
        assert r["applied_schemes"] == []


# ---------------------------------------------------------------------------
# 2. 买赠优惠
# ---------------------------------------------------------------------------


class TestBuyGift:
    def test_buy2_gift1(self):
        rules = {
            "buy_dish_id": "d2",
            "buy_count": 2,
            "gift_dish_id": "d_gift",
            "gift_count": 1,
            "gift_price_fen": 2800,
        }
        r = calculate_buy_gift(ITEMS, rules)
        # d2 有 quantity=2，满足一次买2赠1
        assert r["discount_fen"] == 2800
        assert r["applied_schemes"] == ["buy_gift"]

    def test_not_enough(self):
        rules = {
            "buy_dish_id": "d1",
            "buy_count": 3,
            "gift_dish_id": "d_gift",
            "gift_count": 1,
            "gift_price_fen": 1000,
        }
        r = calculate_buy_gift(ITEMS, rules)
        assert r["discount_fen"] == 0


# ---------------------------------------------------------------------------
# 3. 加价换购
# ---------------------------------------------------------------------------


class TestAddOn:
    def test_eligible(self):
        rules = {
            "min_order_fen": 20000,
            "add_on_dish_id": "d_x",
            "add_on_price_fen": 100,
            "original_price_fen": 1800,
            "max_count": 1,
        }
        r = calculate_add_on(ITEMS, rules)
        assert r["discount_fen"] == 1700  # 1800 - 100
        assert r["applied_schemes"] == ["add_on"]

    def test_below_threshold(self):
        rules = {
            "min_order_fen": 50000,
            "add_on_price_fen": 100,
            "original_price_fen": 1800,
        }
        r = calculate_add_on(ITEMS, rules)
        assert r["discount_fen"] == 0


# ---------------------------------------------------------------------------
# 4. 再买优惠
# ---------------------------------------------------------------------------


class TestRebuy:
    def test_second_half_price(self):
        rules = {"dish_id": "d2", "nth": 2, "discount_rate": 50}
        r = calculate_rebuy(ITEMS, rules)
        # d2 qty=2, 第2份半价: 5600 - 2800 = 2800, 一次
        assert r["discount_fen"] == 2800
        assert r["applied_schemes"] == ["rebuy"]


# ---------------------------------------------------------------------------
# 5. 会员优惠
# ---------------------------------------------------------------------------


class TestMemberDiscount:
    def test_gold(self):
        rules = {"level_discounts": {"silver": 95, "gold": 90, "diamond": 85}}
        r = calculate_member_discount(ITEMS, "gold", rules)
        # 总价 21800, 9折 = 19620, 优惠 2180
        assert r["discount_fen"] == 2180
        assert r["applied_schemes"] == ["member"]

    def test_no_level(self):
        rules = {"level_discounts": {"gold": 90}}
        r = calculate_member_discount(ITEMS, None, rules)
        assert r["discount_fen"] == 0


# ---------------------------------------------------------------------------
# 6. 订单折扣
# ---------------------------------------------------------------------------


class TestOrderDiscount:
    def test_88_off(self):
        r = calculate_order_discount(21800, {"discount_rate": 88})
        # 21800 * 88 // 100 = 19184, 优惠 2616
        assert r["discount_fen"] == 2616
        assert r["applied_schemes"] == ["order_discount"]


# ---------------------------------------------------------------------------
# 7. 满减优惠
# ---------------------------------------------------------------------------


class TestThreshold:
    def test_multi_tier(self):
        rules = {
            "tiers": [
                {"threshold_fen": 10000, "reduce_fen": 500},
                {"threshold_fen": 20000, "reduce_fen": 1500},
                {"threshold_fen": 30000, "reduce_fen": 3000},
            ]
        }
        r = calculate_threshold(21800, rules)
        # 满 20000 减 1500
        assert r["discount_fen"] == 1500
        assert r["applied_schemes"] == ["threshold"]

    def test_no_match(self):
        rules = {"tiers": [{"threshold_fen": 50000, "reduce_fen": 5000}]}
        r = calculate_threshold(21800, rules)
        assert r["discount_fen"] == 0


# ---------------------------------------------------------------------------
# 互斥规则
# ---------------------------------------------------------------------------


class TestExclusion:
    def test_exclusive(self):
        assert (
            check_exclusion(
                "special_price",
                "order_discount",
                [("special_price", "order_discount")],
            )
            is True
        )

    def test_not_exclusive(self):
        assert (
            check_exclusion(
                "special_price",
                "threshold",
                [("special_price", "order_discount")],
            )
            is False
        )


# ---------------------------------------------------------------------------
# 执行顺序引擎
# ---------------------------------------------------------------------------


class TestApplySchemesInOrder:
    def test_priority_order(self):
        schemes = [
            {
                "scheme_type": "threshold",
                "priority": 2,
                "rules": {
                    "tiers": [{"threshold_fen": 20000, "reduce_fen": 1500}],
                },
            },
            {
                "scheme_type": "special_price",
                "priority": 1,
                "rules": {"dish_prices": {"d1": 6800}},
            },
        ]
        r = apply_schemes_in_order(ITEMS, 21800, schemes)
        # special_price 先执行（priority=1），再 threshold
        assert "special_price" in r["applied_schemes"]
        assert "threshold" in r["applied_schemes"]
        assert r["total_discount_fen"] == 2000 + 1500  # 3500

    def test_exclusion_skips(self):
        schemes = [
            {
                "scheme_type": "special_price",
                "priority": 1,
                "rules": {"dish_prices": {"d1": 6800}},
                "exclusion_rules": [["special_price", "order_discount"]],
            },
            {
                "scheme_type": "order_discount",
                "priority": 2,
                "rules": {"discount_rate": 88},
                "exclusion_rules": [["special_price", "order_discount"]],
            },
        ]
        r = apply_schemes_in_order(ITEMS, 21800, schemes)
        # special_price 先执行，order_discount 因互斥被跳过
        assert "special_price" in r["applied_schemes"]
        assert "order_discount" not in r["applied_schemes"]
        assert len(r["skipped_schemes"]) == 1
        assert r["skipped_schemes"][0]["scheme_type"] == "order_discount"


# ---------------------------------------------------------------------------
# API 端点测试
# ---------------------------------------------------------------------------


class TestMarketingAPI:
    def test_calculate(self):
        body = {
            "items": [
                {"dish_id": "d1", "name": "鱼头", "price_fen": 8800, "quantity": 1},
            ],
            "order_total_fen": 8800,
            "schemes": [
                {
                    "scheme_type": "special_price",
                    "priority": 1,
                    "rules": {"dish_prices": {"d1": 6800}},
                }
            ],
        }
        r = client.post("/api/v1/member/marketing-schemes/calculate", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["total_discount_fen"] == 2000

    def test_create_and_list(self):
        body = {
            "scheme_type": "threshold",
            "name": "满200减15",
            "priority": 5,
            "rules": {"tiers": [{"threshold_fen": 20000, "reduce_fen": 1500}]},
            "store_id": "s1",
        }
        r = client.post("/api/v1/member/marketing-schemes", json=body)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = client.get("/api/v1/member/marketing-schemes?store_id=s1")
        assert r.status_code == 200
        assert r.json()["data"]["total"] >= 1

    def test_create_invalid_type(self):
        body = {"scheme_type": "invalid_type", "name": "无效"}
        r = client.post("/api/v1/member/marketing-schemes", json=body)
        assert r.json()["ok"] is False
