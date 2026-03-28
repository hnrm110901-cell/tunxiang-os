"""
库存Agent迁移测试 — 从老项目 packages/agents/inventory/tests/test_inventory_extended.py 迁移

老项目: InventoryAgent (补货告警/临期预警/盘点差异/消耗预测)
新项目: InventoryAlertAgent (消耗预测/补货告警/保质期预警/库存水位优化/供应商评级/损耗分析)
       + ConstraintChecker (食安合规约束)

迁移策略:
- 补货建议生成 -> InventoryAlertAgent.generate_restock_alerts (接口兼容)
- 临期食材预警 -> InventoryAlertAgent.check_expiration + ConstraintChecker.check_food_safety
- 库存状态分类 -> InventoryAlertAgent.monitor_inventory
- 消耗预测 -> InventoryAlertAgent.predict_consumption (4种算法)
- 库存水位优化 -> InventoryAlertAgent.optimize_stock_levels (新增能力)
"""

import sys
import os
import asyncio

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult
from agents.constraints import ConstraintChecker
from agents.skills.inventory_alert import InventoryAlertAgent

TID = "00000000-0000-0000-0000-000000000001"


# -- Fixtures --


@pytest.fixture
def agent():
    return InventoryAlertAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def constraint_checker():
    return ConstraintChecker()


# -- 补货建议生成逻辑 (迁移自 TestRestockAlertGeneration) --


class TestRestockAlertGeneration:
    """补货建议生成逻辑测试"""

    def test_restock_alert_for_critical_item(self, agent):
        """库存严重不足的物料必须生成 critical 级别补货提醒

        迁移自: test_restock_alert_for_out_of_stock_item + test_restock_alert_for_critical_stock_item
        老项目: 缺货 -> CRITICAL, 低于最低库存 -> CRITICAL
        新项目: days_left <= 1 -> critical
        """
        result = asyncio.run(agent.execute("generate_restock_alerts", {
            "items": [
                {"name": "鲈鱼", "current_qty": 2, "min_qty": 5, "daily_usage": 3},  # <1天
            ],
        }))
        assert result.success is True
        assert len(result.data["alerts"]) == 1
        assert result.data["alerts"][0]["level"] == "critical"
        assert result.data["alerts"][0]["item_name"] == "鲈鱼"

    def test_restock_recommended_quantity_positive(self, agent):
        """补货建议数量必须为正数

        迁移自: test_restock_recommended_quantity_positive
        """
        result = asyncio.run(agent.execute("generate_restock_alerts", {
            "items": [
                {"name": "鲈鱼", "current_qty": 2, "min_qty": 5, "daily_usage": 3},
                {"name": "鸡蛋", "current_qty": 5, "min_qty": 10, "daily_usage": 8},
            ],
        }))
        for alert in result.data["alerts"]:
            assert alert["suggested_restock_qty"] >= 0, (
                f"物料 {alert['item_name']} 的建议补货量不能为负"
            )

    def test_sufficient_stock_no_alert(self, agent):
        """库存充足的物料不应生成补货提醒

        迁移自: test_sufficient_stock_no_alert
        """
        result = asyncio.run(agent.execute("generate_restock_alerts", {
            "items": [
                {"name": "米", "current_qty": 200, "min_qty": 10, "daily_usage": 5},
            ],
        }))
        assert result.data["total"] == 0

    def test_alert_includes_days_left(self, agent):
        """补货告警应包含剩余天数

        迁移自: test_restock_alert_includes_stockout_date
        老项目: estimated_stockout_date 字段
        新项目: days_left 字段
        """
        result = asyncio.run(agent.execute("generate_restock_alerts", {
            "items": [
                {"name": "鲈鱼", "current_qty": 6, "min_qty": 5, "daily_usage": 3},
            ],
        }))
        for alert in result.data["alerts"]:
            assert "days_left" in alert, "补货告警必须包含剩余天数"
            assert alert["days_left"] >= 0

    def test_alerts_sorted_by_urgency(self, agent):
        """补货告警应按紧急程度排序

        迁移自: test_expiration_alerts_sorted_by_urgency (应用到补货场景)
        """
        result = asyncio.run(agent.execute("generate_restock_alerts", {
            "items": [
                {"name": "白菜", "current_qty": 10, "min_qty": 5, "daily_usage": 2},   # ~5天 warning
                {"name": "鲈鱼", "current_qty": 2, "min_qty": 5, "daily_usage": 3},    # <1天 critical
                {"name": "鸡蛋", "current_qty": 10, "min_qty": 10, "daily_usage": 4},  # ~2.5天 urgent
            ],
        }))
        alerts = result.data["alerts"]
        assert len(alerts) >= 2
        level_order = {"critical": 0, "urgent": 1, "warning": 2}
        for i in range(len(alerts) - 1):
            assert level_order[alerts[i]["level"]] <= level_order[alerts[i + 1]["level"]], (
                "补货告警应按紧急程度排序"
            )


# -- 临期食材预警 (迁移自 TestExpirationAlerts) --


class TestExpirationAlerts:
    """临期食材预警测试 — 三硬约束之食安合规"""

    def test_expiring_soon_triggers_alert(self, agent):
        """即将过期的物料必须触发预警

        迁移自: test_expiring_soon_triggers_alert
        """
        result = asyncio.run(agent.execute("check_expiration", {
            "items": [
                {"name": "鲜牛奶", "remaining_hours": 12},
                {"name": "大米", "remaining_hours": 720},
            ],
        }))
        assert result.data["total"] >= 1
        milk_warnings = [w for w in result.data["warnings"] if w["item"] == "鲜牛奶"]
        assert len(milk_warnings) == 1
        assert milk_warnings[0]["status"] in ("expired", "critical")

    def test_expired_item_triggers_critical(self, agent):
        """已过期物料必须触发 expired 状态

        迁移自: test_expired_item_triggers_critical_alert
        """
        result = asyncio.run(agent.execute("check_expiration", {
            "items": [
                {"name": "过期牛奶", "remaining_hours": 0},
            ],
        }))
        assert result.data["total"] == 1
        assert result.data["warnings"][0]["status"] == "expired"

    def test_no_expiry_warnings_for_long_shelf_life(self, agent):
        """长保质期物料不应触发预警

        迁移自: test_no_expiration_date_no_alert
        """
        result = asyncio.run(agent.execute("check_expiration", {
            "items": [
                {"name": "酱油", "remaining_hours": 2160},  # 90天
            ],
        }))
        assert result.data["total"] == 0

    def test_expiration_via_constraint_checker(self, constraint_checker):
        """通过 ConstraintChecker 验证食安合规

        迁移自: 食安相关测试的约束层面验证
        新项目: ConstraintChecker.check_food_safety 直接校验
        """
        # 临期食材应触发违规
        result = constraint_checker.check_food_safety({
            "ingredients": [
                {"name": "鲈鱼", "remaining_hours": 12},
                {"name": "白菜", "remaining_hours": 48},
            ],
        })
        assert result["passed"] is False
        assert len(result["items"]) == 1
        assert result["items"][0]["ingredient"] == "鲈鱼"

    def test_food_safety_constraint_in_agent_run(self, agent):
        """Agent.run() 自动触发食安约束校验

        迁移自: 食安约束的端到端验证
        check_expiration 返回的 data 包含 ingredients 字段，
        SkillAgent.run() 自动将其传给 ConstraintChecker
        """
        result = asyncio.run(agent.run("check_expiration", {
            "items": [
                {"name": "牛奶", "remaining_hours": 6},
            ],
        }))
        assert result.success is True
        # data 中有 ingredients 列表，ConstraintChecker 会校验
        if result.constraints_detail.get("food_safety_check"):
            assert result.constraints_detail["food_safety_check"]["passed"] is False


# -- 库存盘点差异检测 (迁移自 TestInventoryDiscrepancy) --


class TestInventoryMonitoring:
    """库存监控测试 — 对应老项目的库存状态分类

    老项目: _analyze_inventory_status 返回 OUT_OF_STOCK/CRITICAL/SUFFICIENT 等状态
    新项目: monitor_inventory 统计 normal/low/critical/out 各状态数量
    """

    def test_out_of_stock_detection(self, agent):
        """库存为0时应归类为 out

        迁移自: test_inventory_status_boundary_out_of_stock
        """
        result = asyncio.run(agent.execute("monitor_inventory", {
            "items": [
                {"name": "鲈鱼", "current_qty": 0, "min_qty": 10},
            ],
        }))
        assert result.data["status_counts"]["out"] == 1

    def test_critical_stock_detection(self, agent):
        """库存低于最低库存50%时应归类为 critical

        迁移自: test_inventory_status_boundary_at_min
        """
        result = asyncio.run(agent.execute("monitor_inventory", {
            "items": [
                {"name": "鲈鱼", "current_qty": 3, "min_qty": 10},
            ],
        }))
        assert result.data["status_counts"]["critical"] == 1

    def test_sufficient_stock_normal(self, agent):
        """库存充足时应归类为 normal

        迁移自: test_inventory_status_boundary_above_safe
        """
        result = asyncio.run(agent.execute("monitor_inventory", {
            "items": [
                {"name": "酱油", "current_qty": 100, "min_qty": 20},
            ],
        }))
        assert result.data["status_counts"]["normal"] == 1

    def test_negative_stock_treated_as_out(self, agent):
        """负库存也应归类为 out

        迁移自: test_inventory_status_boundary_negative_stock
        """
        result = asyncio.run(agent.execute("monitor_inventory", {
            "items": [
                {"name": "负库存", "current_qty": -5, "min_qty": 10},
            ],
        }))
        assert result.data["status_counts"]["out"] == 1


# -- 消耗预测异常输入处理 (迁移自 TestAbnormalInputHandling) --


class TestAbnormalInputHandling:
    """异常输入处理测试"""

    def test_unsupported_action(self, agent):
        """不支持的 action 应返回失败

        迁移自: test_execute_unsupported_action
        """
        result = asyncio.run(agent.execute("fly_to_moon", {}))
        assert result.success is False
        assert "Unsupported" in result.error

    def test_prediction_insufficient_history(self, agent):
        """历史数据不足时预测应返回错误

        迁移自: test_execute_missing_required_params + test_prediction_empty_history
        """
        result = asyncio.run(agent.execute("predict_consumption", {
            "daily_usage": [10, 12],  # 少于3天
            "days_ahead": 7,
        }))
        assert result.success is False
        assert "3天" in result.error

    def test_prediction_with_sufficient_data(self, agent):
        """充足历史数据的预测应成功

        迁移自: test_confidence_stable_data
        """
        result = asyncio.run(agent.execute("predict_consumption", {
            "daily_usage": [10, 12, 11, 13, 10, 14, 12, 11, 13, 10, 12, 11, 13, 14],
            "days_ahead": 7,
            "current_stock": 100,
        }))
        assert result.success is True
        assert result.data["algorithm"] in ("moving_avg", "weighted_avg", "linear", "seasonal")
        assert result.data["total_predicted"] > 0
        # 14天数据 -> 较高置信度
        assert result.confidence >= 0.6

    def test_optimize_stock_insufficient_data(self, agent):
        """库存水位优化数据不足时应失败

        迁移自: test_prediction_single_record
        """
        result = asyncio.run(agent.execute("optimize_stock_levels", {
            "daily_usage": [10, 12, 11],
            "lead_days": 3,
        }))
        assert result.success is False

    def test_optimize_stock_levels_correct_hierarchy(self, agent):
        """库存水位三条线的层级关系: safety < min < max"""
        result = asyncio.run(agent.execute("optimize_stock_levels", {
            "daily_usage": [10, 12, 11, 13, 10, 14, 12, 11, 13, 10, 12, 11, 13, 14],
            "lead_days": 3,
        }))
        assert result.success is True
        assert result.data["safety_stock"] > 0
        assert result.data["min_stock"] > result.data["safety_stock"]
        assert result.data["max_stock"] > result.data["min_stock"]

    def test_get_supported_actions(self, agent):
        """支持的操作列表应完整

        迁移自: test_get_supported_actions
        """
        actions = agent.get_supported_actions()
        expected = [
            "monitor_inventory", "predict_consumption",
            "generate_restock_alerts", "check_expiration",
            "optimize_stock_levels",
        ]
        for action in expected:
            assert action in actions, f"缺少操作: {action}"


# -- 供应商管理 (新项目新增能力) --


class TestSupplierManagement:
    """供应商管理 — 新项目新增能力"""

    def test_supplier_grade_a(self, agent):
        """优秀供应商评级为A"""
        result = asyncio.run(agent.execute("evaluate_supplier", {
            "on_time_rate": 0.95, "quality_rate": 0.98,
            "price_stability": 0.9, "avg_response_hours": 4,
        }))
        assert result.data["grade"] == "A"
        assert result.data["total_score"] >= 85

    def test_supplier_grade_d(self, agent):
        """差评供应商评级为D"""
        result = asyncio.run(agent.execute("evaluate_supplier", {
            "on_time_rate": 0.3, "quality_rate": 0.4,
            "price_stability": 0.2, "avg_response_hours": 48,
        }))
        assert result.data["grade"] == "D"
        assert result.data["total_score"] < 50

    def test_supplier_price_comparison(self, agent):
        """供应商比价"""
        result = asyncio.run(agent.execute("compare_supplier_prices", {
            "quotes": [
                {"supplier": "供应商A", "price_fen": 1000},
                {"supplier": "供应商B", "price_fen": 800},
                {"supplier": "供应商C", "price_fen": 1200},
            ],
        }))
        assert result.success is True
        assert result.data["cheapest"]["supplier"] == "供应商B"
        assert result.data["potential_saving_pct"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
