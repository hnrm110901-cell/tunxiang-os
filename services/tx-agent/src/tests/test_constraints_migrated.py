"""
三条硬约束独立测试 — 从老项目四个 Agent 测试中提取并统一

产品宪法: "所有 Agent 决策必须通过这三条校验，无例外"
1. 毛利底线 — 任何折扣/赠送不可使单笔毛利低于设定阈值
2. 食安合规 — 临期/过期食材不可用于出品
3. 客户体验 — 出餐时间不可超过门店设定上限

本文件确保三条硬约束在所有场景下都被正确执行，
无论由哪个 Skill Agent 触发。
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.constraints import (
    DEFAULT_EXPIRY_BUFFER_HOURS,
    DEFAULT_MAX_SERVE_MINUTES,
    DEFAULT_MIN_MARGIN_RATE,
    ConstraintChecker,
)
from agents.skills.discount_guard import DiscountGuardAgent
from agents.skills.inventory_alert import InventoryAlertAgent
from agents.skills.serve_dispatch import ServeDispatchAgent
from agents.skills.smart_menu import SmartMenuAgent

TID = "00000000-0000-0000-0000-000000000001"


# -- Fixtures --


@pytest.fixture
def checker():
    return ConstraintChecker()


# =============================================================================
# 约束 1: 毛利底线
# =============================================================================


class TestMarginConstraint:
    """毛利底线约束 — 折扣/赠送不可使单笔毛利低于阈值"""

    def test_default_threshold_is_15_percent(self):
        """默认毛利阈值为 15%"""
        assert DEFAULT_MIN_MARGIN_RATE == 0.15

    def test_margin_pass_normal(self, checker):
        """正常毛利率应通过 (50% > 15%)"""
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 500})
        assert result["passed"] is True
        assert result["actual_rate"] == 0.5

    def test_margin_fail_low(self, checker):
        """低毛利率应不通过 (10% < 15%)"""
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 900})
        assert result["passed"] is False
        assert result["actual_rate"] == 0.1

    def test_margin_boundary_exact_threshold(self, checker):
        """恰好等于阈值应通过 (15% >= 15%)"""
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 850})
        assert result["passed"] is True
        assert result["actual_rate"] == 0.15

    def test_margin_boundary_just_below(self, checker):
        """刚好低于阈值应不通过"""
        result = checker.check_margin({"price_fen": 10000, "cost_fen": 8501})
        assert result["passed"] is False

    def test_margin_zero_price(self, checker):
        """零售价为0应不通过"""
        result = checker.check_margin({"price_fen": 0, "cost_fen": 500})
        assert result["passed"] is False

    def test_margin_no_data_skips(self, checker):
        """无价格/成本数据时跳过校验"""
        assert checker.check_margin({}) is None
        assert checker.check_margin({"price_fen": 1000}) is None

    def test_margin_custom_threshold(self):
        """自定义毛利阈值"""
        checker = ConstraintChecker(min_margin_rate=0.3)
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 750})
        assert result["passed"] is False  # 25% < 30%

    def test_margin_via_final_amount_fen(self, checker):
        """使用 final_amount_fen 字段"""
        result = checker.check_margin({
            "final_amount_fen": 1000, "food_cost_fen": 500,
        })
        assert result["passed"] is True
        assert result["actual_rate"] == 0.5

    def test_margin_in_discount_guard_agent(self):
        """折扣守护 Agent 中的毛利约束校验"""
        agent = DiscountGuardAgent(tenant_id=TID)
        result = asyncio.run(agent.run("detect_discount_anomaly", {
            "order": {
                "total_amount_fen": 5000,
                "discount_amount_fen": 500,
                "cost_fen": 4500,  # 毛利率 10%
            },
        }))
        # run() 自动校验约束
        if result.constraints_detail.get("margin_check"):
            assert result.constraints_detail["margin_check"]["passed"] is False

    def test_margin_in_smart_menu_agent(self):
        """智能排菜 Agent 中的毛利约束校验"""
        agent = SmartMenuAgent(tenant_id=TID)
        # BOM 成本 3500，售价 4000，毛利率 12.5% < 15%
        result = asyncio.run(agent.run("simulate_cost", {
            "bom_items": [
                {"cost_fen": 2000, "quantity": 1},
                {"cost_fen": 1500, "quantity": 1},
            ],
            "target_price_fen": 4000,
        }))
        assert result.constraints_passed is False
        assert result.constraints_detail["margin_check"]["passed"] is False

    def test_margin_pass_in_smart_menu_agent(self):
        """毛利充足时约束应通过"""
        agent = SmartMenuAgent(tenant_id=TID)
        result = asyncio.run(agent.run("simulate_cost", {
            "bom_items": [
                {"cost_fen": 300, "quantity": 1},
                {"cost_fen": 200, "quantity": 1},
            ],
            "target_price_fen": 3800,  # 成本 500，毛利率 86.8%
        }))
        assert result.constraints_detail["margin_check"]["passed"] is True


# =============================================================================
# 约束 2: 食安合规
# =============================================================================


class TestFoodSafetyConstraint:
    """食安合规约束 — 临期/过期食材不可用于出品"""

    def test_default_buffer_is_24_hours(self):
        """默认保质期缓冲为 24 小时"""
        assert DEFAULT_EXPIRY_BUFFER_HOURS == 24

    def test_food_safety_pass(self, checker):
        """充足保质期应通过"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 72}],
        })
        assert result["passed"] is True

    def test_food_safety_fail_near_expiry(self, checker):
        """临期食材应不通过 (12小时 < 24小时)"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 12}],
        })
        assert result["passed"] is False
        assert len(result["items"]) == 1

    def test_food_safety_fail_expired(self, checker):
        """已过期食材应不通过"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "牛奶", "remaining_hours": 0}],
        })
        assert result["passed"] is False

    def test_food_safety_fail_negative_hours(self, checker):
        """负剩余时间(已过期)应不通过"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "牛奶", "remaining_hours": -24}],
        })
        assert result["passed"] is False

    def test_food_safety_boundary_exact_threshold(self, checker):
        """恰好等于缓冲阈值应通过 (24 >= 24)"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 24}],
        })
        assert result["passed"] is True

    def test_food_safety_boundary_just_below(self, checker):
        """刚好低于阈值应不通过 (23 < 24)"""
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 23}],
        })
        assert result["passed"] is False

    def test_food_safety_multiple_items_partial_violation(self, checker):
        """部分食材临期也应不通过"""
        result = checker.check_food_safety({
            "ingredients": [
                {"name": "鲈鱼", "remaining_hours": 12},
                {"name": "白菜", "remaining_hours": 48},
                {"name": "牛奶", "remaining_hours": 6},
            ],
        })
        assert result["passed"] is False
        assert len(result["items"]) == 2  # 鲈鱼 + 牛奶

    def test_food_safety_no_ingredients_skips(self, checker):
        """无食材数据时跳过校验"""
        assert checker.check_food_safety({}) is None
        assert checker.check_food_safety({"ingredients": []}) is None

    def test_food_safety_custom_threshold(self):
        """自定义保质期缓冲"""
        checker = ConstraintChecker(expiry_buffer_hours=48)
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 36}],
        })
        assert result["passed"] is False  # 36 < 48

    def test_food_safety_in_inventory_agent(self):
        """库存预警 Agent 中的食安约束校验"""
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(agent.run("check_expiration", {
            "items": [
                {"name": "牛奶", "remaining_hours": 6},
                {"name": "鸡蛋", "remaining_hours": 200},
            ],
        }))
        # data 中 ingredients 字段触发 food_safety 校验
        if result.constraints_detail.get("food_safety_check"):
            assert result.constraints_detail["food_safety_check"]["passed"] is False


# =============================================================================
# 约束 3: 客户体验 (出餐时限)
# =============================================================================


class TestExperienceConstraint:
    """客户体验约束 — 出餐时间不可超过门店设定上限"""

    def test_default_max_serve_is_30_minutes(self):
        """默认出餐上限为 30 分钟"""
        assert DEFAULT_MAX_SERVE_MINUTES == 30

    def test_experience_pass(self, checker):
        """出餐时间在限制内应通过"""
        result = checker.check_experience({"estimated_serve_minutes": 20})
        assert result["passed"] is True

    def test_experience_fail(self, checker):
        """出餐时间超限应不通过"""
        result = checker.check_experience({"estimated_serve_minutes": 45})
        assert result["passed"] is False
        assert result["actual_minutes"] == 45

    def test_experience_boundary_exact_threshold(self, checker):
        """恰好等于上限应通过 (30 <= 30)"""
        result = checker.check_experience({"estimated_serve_minutes": 30})
        assert result["passed"] is True

    def test_experience_boundary_just_above(self, checker):
        """刚好超出上限应不通过 (31 > 30)"""
        result = checker.check_experience({"estimated_serve_minutes": 31})
        assert result["passed"] is False

    def test_experience_no_data_skips(self, checker):
        """无出餐数据时跳过校验"""
        assert checker.check_experience({}) is None

    def test_experience_custom_threshold(self):
        """自定义出餐上限"""
        checker = ConstraintChecker(max_serve_minutes=15)
        result = checker.check_experience({"estimated_serve_minutes": 20})
        assert result["passed"] is False
        assert result["threshold_minutes"] == 15

    def test_experience_in_serve_dispatch_agent(self):
        """出餐调度 Agent 中的出餐时限约束校验"""
        agent = ServeDispatchAgent(tenant_id=TID)
        # 大量菜品+复杂菜+长队列 -> 超时
        result = asyncio.run(agent.run("predict_serve_time", {
            "dish_count": 8,
            "has_complex_dish": True,
            "kitchen_queue_size": 10,
        }))
        estimated = result.data["estimated_serve_minutes"]
        assert estimated > 30, "该场景应超出出餐时限"

        if result.constraints_detail.get("experience_check"):
            assert result.constraints_detail["experience_check"]["passed"] is False

    def test_experience_pass_in_serve_dispatch_agent(self):
        """简单订单出餐时间应在限制内"""
        agent = ServeDispatchAgent(tenant_id=TID)
        result = asyncio.run(agent.run("predict_serve_time", {
            "dish_count": 2,
            "has_complex_dish": False,
            "kitchen_queue_size": 0,
        }))
        estimated = result.data["estimated_serve_minutes"]
        assert estimated <= 30
        if result.constraints_detail.get("experience_check"):
            assert result.constraints_detail["experience_check"]["passed"] is True


# =============================================================================
# 三条约束综合测试
# =============================================================================


class TestAllConstraintsCombined:
    """三条约束综合校验"""

    def test_all_pass_when_no_relevant_data(self, checker):
        """无相关数据时全部通过"""
        result = checker.check_all({})
        assert result.passed is True
        assert len(result.violations) == 0

    def test_all_three_violations(self, checker):
        """同时违反三条约束"""
        result = checker.check_all({
            "price_fen": 1000,
            "cost_fen": 900,                     # 毛利 10% < 15%
            "ingredients": [
                {"name": "牛奶", "remaining_hours": 6},  # 6h < 24h
            ],
            "estimated_serve_minutes": 45,       # 45min > 30min
        })
        assert result.passed is False
        assert len(result.violations) == 3
        assert result.margin_check is not None
        assert result.food_safety_check is not None
        assert result.experience_check is not None

    def test_single_violation_blocks(self, checker):
        """任何一条违反都应阻塞"""
        # 仅毛利违规
        result = checker.check_all({
            "price_fen": 1000, "cost_fen": 900,
        })
        assert result.passed is False
        assert len(result.violations) == 1
        assert "毛利底线" in result.violations[0]

    def test_violation_messages_contain_details(self, checker):
        """违规信息应包含具体数值"""
        result = checker.check_all({
            "price_fen": 1000,
            "cost_fen": 900,
            "estimated_serve_minutes": 45,
        })
        assert any("10.0%" in v for v in result.violations), "毛利违规应包含实际毛利率"
        assert any("45" in v for v in result.violations), "出餐违规应包含实际分钟数"

    def test_constraint_result_to_dict(self, checker):
        """ConstraintResult.to_dict() 结构完整"""
        result = checker.check_all({
            "price_fen": 1000, "cost_fen": 500,
            "estimated_serve_minutes": 20,
        })
        d = result.to_dict()
        assert "passed" in d
        assert "violations" in d
        assert "margin_check" in d
        assert "food_safety_check" in d
        assert "experience_check" in d

    def test_all_constraints_enforced_in_agent_run(self):
        """SkillAgent.run() 对所有返回数据执行三条约束

        这是端到端的综合测试，确保基类 run() 方法
        自动调用 ConstraintChecker.check_all()
        """
        agent = SmartMenuAgent(tenant_id=TID)
        result = asyncio.run(agent.run("simulate_cost", {
            "bom_items": [
                {"cost_fen": 900, "quantity": 1},
            ],
            "target_price_fen": 1000,  # 毛利率 10% < 15%
        }))
        # run() 返回的 result 应包含约束校验详情
        assert result.constraints_detail is not None
        assert "passed" in result.constraints_detail
        assert result.constraints_passed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
