"""消费返现Campaign测试 — consumption_cashback.py

覆盖场景（共 8 个）：
1. 消费1000匹配最高阶梯（返150）
2. 消费500匹配中间阶梯
3. 消费不足最低门槛
4. 排除的订单类型
5. 返现到储值卡
6. 返优惠券
7. 毛利底线保护
8. CONFIG_SCHEMA结构校验
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from campaigns.consumption_cashback import CONFIG_SCHEMA, execute


class TestConsumptionCashback(unittest.TestCase):
    """消费返现Campaign测试"""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ── 1. 消费1000匹配最高阶梯（返150） ──

    def test_cashback_tier_match_highest(self):
        """消费1000元匹配最高阶梯（返150元）"""
        config = {
            "name": "测试返现",
            "cashback_rules": [
                {"min_spend_fen": 30000, "cashback_fen": 3000},
                {"min_spend_fen": 50000, "cashback_fen": 6000},
                {"min_spend_fen": 100000, "cashback_fen": 15000},
            ],
        }
        result = self._run(execute("cust1", config, {"total_fen": 100000, "order_id": "o1"}, "t1"))
        self.assertTrue(result["success"])
        self.assertEqual(result["cashback_fen"], 15000)
        self.assertEqual(result["matched_rule"]["min_spend_fen"], 100000)

    # ── 2. 消费500匹配中间阶梯 ──

    def test_cashback_tier_match_middle(self):
        """消费550元匹配中间阶梯（返60元）"""
        config = {
            "name": "测试",
            "cashback_rules": [
                {"min_spend_fen": 30000, "cashback_fen": 3000},
                {"min_spend_fen": 50000, "cashback_fen": 6000},
                {"min_spend_fen": 100000, "cashback_fen": 15000},
            ],
        }
        result = self._run(execute("cust1", config, {"total_fen": 55000, "order_id": "o1"}, "t1"))
        self.assertTrue(result["success"])
        self.assertEqual(result["cashback_fen"], 6000)
        self.assertEqual(result["matched_rule"]["min_spend_fen"], 50000)

    # ── 3. 消费不足最低门槛 ──

    def test_cashback_below_minimum(self):
        """消费200元不足最低门槛300元，应返回 below_minimum_spend。"""
        config = {
            "name": "测试",
            "cashback_rules": [
                {"min_spend_fen": 30000, "cashback_fen": 3000},
            ],
        }
        result = self._run(execute("cust1", config, {"total_fen": 20000, "order_id": "o1"}, "t1"))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "below_minimum_spend")

    # ── 4. 排除的订单类型 ──

    def test_cashback_excluded_order_type(self):
        """delivery 类型被排除，应返回 order_type_excluded。"""
        config = {
            "name": "测试",
            "cashback_rules": [{"min_spend_fen": 10000, "cashback_fen": 1000}],
            "excluded_order_types": ["delivery"],
        }
        result = self._run(execute(
            "cust1", config,
            {"total_fen": 20000, "order_type": "delivery", "order_id": "o1"},
            "t1",
        ))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "order_type_excluded")

    # ── 5. 返现到储值卡 ──

    def test_cashback_stored_value_type(self):
        """cashback_type=stored_value 时 action 应为 recharge_stored_value。"""
        config = {
            "name": "测试",
            "cashback_rules": [{"min_spend_fen": 10000, "cashback_fen": 1000, "cashback_type": "stored_value"}],
        }
        result = self._run(execute("cust1", config, {"total_fen": 20000, "order_id": "o1"}, "t1"))
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "recharge_stored_value")
        self.assertEqual(result["cashback_type"], "stored_value")
        self.assertEqual(result["recharge_amount_fen"], 1000)

    # ── 6. 返优惠券 ──

    def test_cashback_coupon_type(self):
        """cashback_type=coupon 时 action 应为 issue_coupon 且带 validity_days。"""
        config = {
            "name": "测试",
            "cashback_rules": [
                {"min_spend_fen": 10000, "cashback_fen": 1000, "cashback_type": "coupon", "coupon_validity_days": 14},
            ],
        }
        result = self._run(execute("cust1", config, {"total_fen": 20000, "order_id": "o1"}, "t1"))
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "issue_coupon")
        self.assertEqual(result["coupon_validity_days"], 14)
        self.assertEqual(result["coupon_amount_fen"], 1000)

    # ── 7. 毛利底线保护 ──

    def test_cashback_margin_protection(self):
        """返现金额超出毛利底线（返现比 > 100-margin_floor），应被拒绝。"""
        config = {
            "name": "测试",
            "cashback_rules": [{"min_spend_fen": 1000, "cashback_fen": 8000}],
            "margin_floor_pct": 30,
        }
        # 消费100元 返80元 → 返现比=80% > 70%(100-30) → 触发毛利保护
        result = self._run(execute("cust1", config, {"total_fen": 10000, "order_id": "o1"}, "t1"))
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "margin_floor_violation")

    # ── 8. CONFIG_SCHEMA 结构校验 ──

    def test_config_schema_valid(self):
        """CONFIG_SCHEMA 应包含 cashback_rules 和 margin_floor_pct 字段定义。"""
        self.assertIn("cashback_rules", CONFIG_SCHEMA["properties"])
        self.assertIn("margin_floor_pct", CONFIG_SCHEMA["properties"])
        self.assertIn("excluded_order_types", CONFIG_SCHEMA["properties"])
        self.assertEqual(CONFIG_SCHEMA["type"], "object")
        self.assertIn("cashback_rules", CONFIG_SCHEMA["required"])


if __name__ == "__main__":
    unittest.main()
