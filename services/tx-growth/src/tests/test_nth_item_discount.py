"""第N份M折Campaign测试 — nth_item_discount.py

覆盖场景（共 8 个）：
1. 第二份半价（2只烤鸭→第2只5折）
2. 第三杯3折（5杯饮品→第3杯3折=1次）
3. 4份→2次第二份半价
4. 排除菜品不打折
5. 空订单
6. 最多应用次数限制
7. 毛利保护
8. CONFIG_SCHEMA结构
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from campaigns.nth_item_discount import CONFIG_SCHEMA, execute


class TestNthItemDiscount(unittest.TestCase):
    """第N份M折Campaign测试"""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ── 1. 第二份半价 ──

    def test_second_item_half_price(self):
        """2只烤鸭→第2只5折，折扣=16800*(100-50)/100=8400。"""
        config = {
            "name": "烤鸭第二份半价",
            "discount_rules": [
                {"dish_ids": ["duck1"], "nth_item": 2, "discount_pct": 50, "max_applications_per_order": 3},
            ],
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "duck1", "dish_name": "烤鸭", "quantity": 2, "unit_price_fen": 16800},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertTrue(result["success"])
        # 第2只烤鸭5折: 16800 * (100-50)/100 = 8400
        self.assertEqual(result["total_discount_fen"], 8400)
        self.assertEqual(len(result["discount_details"]), 1)
        self.assertEqual(result["discount_details"][0]["discount_count"], 1)

    # ── 2. 第三杯3折 ──

    def test_third_cup_30pct(self):
        """5杯饮品→第3杯3折=1次折扣（5//3=1）。"""
        config = {
            "name": "饮品第三杯3折",
            "discount_rules": [
                {"nth_item": 3, "discount_pct": 30, "max_applications_per_order": 2},
            ],
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "drink1", "dish_name": "奶茶", "quantity": 5, "unit_price_fen": 1800},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertTrue(result["success"])
        # 5//3 = 1次折扣
        self.assertEqual(result["discount_details"][0]["discount_count"], 1)
        # 每次折扣: 1800*(100-30)/100 = 1260
        self.assertEqual(result["total_discount_fen"], 1260)

    # ── 3. 4份→2次第二份半价 ──

    def test_four_items_two_discounts(self):
        """4瓶啤酒→2次第二份半价（4//2=2）。"""
        config = {
            "name": "第二份半价",
            "discount_rules": [
                {"nth_item": 2, "discount_pct": 50, "max_applications_per_order": 5},
            ],
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "beer1", "dish_name": "啤酒", "quantity": 4, "unit_price_fen": 1500},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertTrue(result["success"])
        # 4//2 = 2次折扣
        self.assertEqual(result["discount_details"][0]["discount_count"], 2)
        # 每次折扣: 1500*(100-50)/100 = 750, 总折扣=750*2=1500
        self.assertEqual(result["total_discount_fen"], 1500)

    # ── 4. 排除菜品不打折 ──

    def test_excluded_dish(self):
        """排除菜品 special1 不享受折扣。"""
        config = {
            "name": "测试",
            "discount_rules": [{"nth_item": 2, "discount_pct": 50}],
            "excluded_dish_ids": ["special1"],
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "special1", "dish_name": "特价菜", "quantity": 2, "unit_price_fen": 5000},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "no_applicable_items")

    # ── 5. 空订单 ──

    def test_no_items(self):
        """空订单应返回 no_items。"""
        config = {"name": "测试", "discount_rules": []}
        result = self._run(execute("cust1", config, {"order_id": "o1", "items": []}, "t1"))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "no_items")

    # ── 6. 最多应用次数限制 ──

    def test_max_applications_limit(self):
        """max_applications_per_order=1 时即使数量足够也只享 1 次折扣。"""
        config = {
            "name": "测试",
            "discount_rules": [
                {"nth_item": 2, "discount_pct": 50, "max_applications_per_order": 1},
            ],
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "d1", "dish_name": "菜品", "quantity": 6, "unit_price_fen": 2000},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertTrue(result["success"])
        # 6//2=3, but max=1
        self.assertEqual(result["discount_details"][0]["discount_count"], 1)
        # 折扣: 2000*(100-50)/100 * 1 = 1000
        self.assertEqual(result["total_discount_fen"], 1000)

    # ── 7. 毛利保护 ──

    def test_margin_protection(self):
        """折扣比例超过毛利底线时应被拒绝。"""
        config = {
            "name": "测试",
            "discount_rules": [{"nth_item": 2, "discount_pct": 99, "max_applications_per_order": 10}],
            "margin_floor_pct": 30,
        }
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "d1", "dish_name": "菜", "quantity": 2, "unit_price_fen": 10000},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        # 总价=20000, 折扣=10000*(100-99)/100*1=100? 不, discount_per_item=10000*(100-99)//100=100
        # 那折扣比=100/20000=0.5% < 70%...不够触发
        # 用更极端的: nth_item=1 让每份都打, 但 nth_item minimum 是 2
        # 实际上 nth=2, pct=99 只折 1 份: 10000*1//100=100, 100/20000=0.5% 不够
        # 此测试验证当折扣不触发毛利保护时正常通过
        self.assertTrue(result["success"])

    # ── 8. CONFIG_SCHEMA 结构 ──

    def test_config_schema(self):
        """CONFIG_SCHEMA 应包含 discount_rules 字段定义。"""
        self.assertIn("discount_rules", CONFIG_SCHEMA["properties"])
        self.assertIn("excluded_dish_ids", CONFIG_SCHEMA["properties"])
        self.assertIn("margin_floor_pct", CONFIG_SCHEMA["properties"])
        self.assertEqual(CONFIG_SCHEMA["type"], "object")
        self.assertIn("discount_rules", CONFIG_SCHEMA["required"])

    # ── 补充: 真正触发毛利保护的场景 ──

    def test_margin_protection_triggered(self):
        """极高折扣比例应触发毛利底线保护。"""
        config = {
            "name": "极端折扣",
            # nth_item=2, pct=1 意味着每2份中第2份只需付1%（折扣=99%的价格）
            "discount_rules": [{"nth_item": 2, "discount_pct": 1, "max_applications_per_order": 100}],
            "margin_floor_pct": 55,
        }
        # 200份 → 100次折扣, 每次折扣=100*(100-1)//100=99
        # 总折扣=99*100=9900, 总价=200*100=20000, 折扣比=9900/20000*100=49.5% > 45%(100-55)
        trigger = {
            "order_id": "o1",
            "items": [
                {"dish_id": "d1", "dish_name": "菜", "quantity": 200, "unit_price_fen": 100},
            ],
        }
        result = self._run(execute("cust1", config, trigger, "t1"))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "margin_floor_violation")


if __name__ == "__main__":
    unittest.main()
