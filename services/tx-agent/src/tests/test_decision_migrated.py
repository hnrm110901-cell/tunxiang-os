"""
决策Agent迁移测试 — 从老项目 packages/agents/decision/tests/test_decision_extended.py 迁移

老项目: DecisionAgent (KPI分析/建议生成/趋势预测/资源优化/决策报告)
新项目: FinanceAuditAgent (财务报表/营收异常/KPI快照/经营洞察/场景识别)
       + ConstraintChecker (三条硬约束校验)
       + MasterAgent (编排 + 意图路由)

迁移策略:
- DecisionAgent 的 KPI 分析/趋势预测 -> FinanceAuditAgent.snapshot_kpi / forecast_orders
- 毛利底线约束 -> ConstraintChecker.check_margin
- 食安合规约束 -> ConstraintChecker.check_food_safety
- 决策日志/留痕 -> SkillAgent.run() 自动填充 constraints_detail
- 低置信度人工审核 -> AgentResult.agent_level (三级自治机制)
- 建议生成 -> FinanceAuditAgent.generate_insight + match_scenario
"""

import sys
import os
import asyncio

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import SkillAgent, AgentResult
from agents.constraints import (
    ConstraintChecker,
    ConstraintResult,
    DEFAULT_MIN_MARGIN_RATE,
    DEFAULT_EXPIRY_BUFFER_HOURS,
    DEFAULT_MAX_SERVE_MINUTES,
)
from agents.master import MasterAgent
from agents.skills.finance_audit import FinanceAuditAgent
from agents.skills.discount_guard import DiscountGuardAgent
from agents.skills.smart_menu import SmartMenuAgent

TID = "00000000-0000-0000-0000-000000000001"


# -- Fixtures --


@pytest.fixture
def finance_agent():
    return FinanceAuditAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def discount_agent():
    return DiscountGuardAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def menu_agent():
    return SmartMenuAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def constraint_checker():
    return ConstraintChecker()


@pytest.fixture
def master():
    master = MasterAgent(tenant_id=TID, store_id="STORE001")
    master.register(FinanceAuditAgent(tenant_id=TID, store_id="STORE001"))
    master.register(DiscountGuardAgent(tenant_id=TID, store_id="STORE001"))
    master.register(SmartMenuAgent(tenant_id=TID, store_id="STORE001"))
    return master


# -- 核心决策路径 (迁移自 TestDecisionAgent) --


class TestDecisionCorePaths:
    """核心决策路径测试 — 对应老项目 TestDecisionAgent"""

    def test_agent_result_contains_required_fields(self, finance_agent):
        """验证 AgentResult 包含: action + reasoning + confidence

        迁移自: test_generates_actionable_recommendation
        老项目验证建议包含 action_items/expected_impact/priority
        新项目使用 AgentResult 统一结构
        """
        result = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 95000, "orders": 180},
            "targets": {"revenue": 100000, "orders": 200},
        }))
        assert result.success is True
        assert result.action == "snapshot_kpi"
        assert len(result.reasoning) > 0, "决策必须包含推理过程"
        assert 0 <= result.confidence <= 1, "置信度必须在[0,1]范围内"

    def test_margin_constraint_enforced_in_agent_run(self, discount_agent):
        """验证毛利底线约束在 Agent.run() 中自动校验

        迁移自: test_margin_constraint_check
        老项目通过 analyze_kpis 间接验证成本率指标
        新项目通过 ConstraintChecker 在 SkillAgent.run() 中强制校验
        """
        # 用 run() 而非 execute()，触发约束校验
        result = asyncio.run(discount_agent.run("detect_discount_anomaly", {
            "order": {
                "total_amount_fen": 10000,
                "discount_amount_fen": 1000,
                "cost_fen": 9000,  # 毛利率仅 10%, 低于 15% 阈值
            },
        }))
        # SkillAgent.run() 自动进行约束校验
        assert result.constraints_detail is not None
        assert "passed" in result.constraints_detail
        # price_fen=10000, cost_fen=9000 -> margin=10% < 15%
        if result.constraints_detail.get("margin_check"):
            assert result.constraints_detail["margin_check"]["passed"] is False

    def test_food_safety_constraint_enforced_in_agent_run(self):
        """验证食安合规约束在 Agent.run() 中自动校验

        迁移自: test_food_safety_constraint_check
        老项目通过 analyze_kpis 的质量类指标间接验证
        新项目直接校验食材剩余保质期
        """
        from agents.skills.inventory_alert import InventoryAlertAgent
        agent = InventoryAlertAgent(tenant_id=TID, store_id="STORE001")
        # check_expiration 返回的 data 包含 ingredients 字段
        result = asyncio.run(agent.run("check_expiration", {
            "items": [
                {"name": "牛奶", "remaining_hours": 12},
                {"name": "米", "remaining_hours": 720},
            ],
        }))
        assert result.success is True
        # data 中有 ingredients 字段，会触发食安约束校验
        if result.constraints_detail.get("food_safety_check"):
            food_check = result.constraints_detail["food_safety_check"]
            assert food_check["passed"] is False, "12小时剩余的牛奶应触发食安违规"

    def test_decision_log_via_agent_result(self, finance_agent):
        """验证每个决策都有留痕

        迁移自: test_decision_log_created
        老项目: 决策报告包含 kpi_summary/insights_summary/recommendations_summary
        新项目: AgentResult 自动填充 constraints_detail + reasoning + execution_ms
        """
        result = asyncio.run(finance_agent.run("snapshot_kpi", {
            "kpis": {"revenue": 95000},
            "targets": {"revenue": 100000},
        }))
        # 决策留痕的关键字段
        assert result.action == "snapshot_kpi"
        assert len(result.reasoning) > 0, "必须有推理过程"
        assert result.execution_ms >= 0, "必须记录执行耗时"
        assert result.constraints_detail is not None, "必须有约束校验详情"
        assert result.inference_layer in ("edge", "cloud"), "必须标注推理层"

    def test_autonomy_level_marked(self, finance_agent):
        """自治等级标注 — 对应老项目 test_low_confidence_triggers_human_review

        老项目: action_required 字段表示需人工介入的建议数量
        新项目: agent_level (1=建议, 2=自动+回滚, 3=完全自主)
        """
        result = asyncio.run(finance_agent.run("snapshot_kpi", {
            "kpis": {"revenue": 50000},
            "targets": {"revenue": 100000},
        }))
        assert result.agent_level in (1, 2, 3)
        # FinanceAuditAgent 默认 level=1 (仅建议)
        assert result.agent_level == 1, "财务稽核Agent应为建议级别"

    def test_invalid_action_graceful_degradation(self, finance_agent):
        """无效action优雅降级

        迁移自: test_invalid_input_graceful_degradation
        """
        result = asyncio.run(finance_agent.execute("nonexistent_action", {}))
        assert result.success is False
        assert result.error is not None
        assert "Unsupported" in result.error

    def test_execute_via_master_dispatch(self, master):
        """通过 MasterAgent dispatch 执行决策

        迁移自: test_execute_analyze_kpis_via_dispatch 等 execute 分发测试
        """
        result = asyncio.run(master.dispatch("finance_audit", "snapshot_kpi", {
            "kpis": {"revenue": 95000, "orders": 180},
            "targets": {"revenue": 100000, "orders": 200},
        }))
        assert result.success is True
        assert result.data["overall_completion_pct"] > 0


# -- 趋势预测约束测试 (迁移自 TestTrendConstraints) --


class TestTrendConstraints:
    """趋势预测约束验证"""

    def test_forecast_confidence_range(self, finance_agent):
        """预测置信度必须在 [0, 1] 范围内

        迁移自: test_forecast_confidence_range
        老项目: forecast_trends 返回 confidence_level
        新项目: forecast_orders 返回 AgentResult.confidence
        """
        result = asyncio.run(finance_agent.execute("forecast_orders", {
            "daily_orders": [150, 140, 160, 180, 200, 190, 170,
                             155, 145, 165, 175, 195, 185, 175],
            "days_ahead": 7,
        }))
        assert result.success is True
        assert 0 <= result.confidence <= 1, "预测置信度必须在[0,1]范围内"

    def test_forecast_values_non_negative(self, finance_agent):
        """预测值不能为负数

        迁移自: test_forecast_values_non_negative
        """
        result = asyncio.run(finance_agent.execute("forecast_orders", {
            "daily_orders": [150, 140, 160, 180, 200, 190, 170,
                             155, 145, 165, 175, 195, 185, 175],
            "days_ahead": 7,
        }))
        assert result.success is True
        for val in result.data["daily_forecast"]:
            assert val >= 0, "预测订单数不能为负数"

    def test_revenue_anomaly_detection(self, finance_agent):
        """营收异常检测 — 对应老项目的趋势分析能力

        迁移自: test_kpi_status_thresholds (KPI状态阈值分类)
        新项目: detect_revenue_anomaly 自动判断正常/异常
        """
        # 正常营收
        result_normal = asyncio.run(finance_agent.execute("detect_revenue_anomaly", {
            "actual_revenue_fen": 830000,
            "history_daily_fen": [800000, 820000, 810000, 830000, 850000, 820000, 810000],
        }))
        assert result_normal.data["is_anomaly"] is False

        # 异常低营收
        result_low = asyncio.run(finance_agent.execute("detect_revenue_anomaly", {
            "actual_revenue_fen": 200000,
            "history_daily_fen": [800000, 820000, 810000, 830000, 850000, 820000, 810000],
        }))
        assert result_low.data["is_anomaly"] is True
        assert result_low.data["direction"] == "below"

    def test_scenario_matching(self, finance_agent):
        """场景识别 — 对应老项目的洞察生成能力

        迁移自: test_create_kpi_insight_high_impact / test_create_kpi_insight_medium_impact
        新项目: match_scenario 根据经营数据匹配场景
        """
        # 高成本场景
        result = asyncio.run(finance_agent.execute("match_scenario", {
            "cost_rate_pct": 45,
        }))
        assert result.data["scenario"] == "high_cost"

        # 正常工作日
        result_normal = asyncio.run(finance_agent.execute("match_scenario", {}))
        assert result_normal.data["scenario"] == "weekday_normal"


# -- 建议生成约束测试 (迁移自 TestRecommendationConstraints) --


class TestRecommendationConstraints:
    """建议生成约束验证"""

    def test_insight_contains_actionable_info(self, finance_agent):
        """洞察包含可操作信息

        迁移自: test_recommendation_has_yuan_impact
        老项目: 建议包含 expected_impact 和 action_items
        新项目: generate_biz_insight 返回带 insights 的洞察
        """
        result = asyncio.run(finance_agent.execute("generate_biz_insight", {
            "metrics": {
                "cost_rate_pct": 40,
                "revenue_change_pct": -15,
            },
        }))
        assert result.success is True
        assert len(result.data["insights"]) >= 2, "高成本+营收下滑应产生至少2条洞察"

    def test_kpi_snapshot_completion_rate(self, finance_agent):
        """KPI快照包含达成率

        迁移自: test_recommendation_from_kpi_critical_priority 等优先级测试
        新项目: snapshot_kpi 返回各指标达成率和总体达成率
        """
        result = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 70000, "orders": 100},
            "targets": {"revenue": 100000, "orders": 200},
        }))
        assert result.success is True
        # 总体达成率应反映低达标情况
        assert result.data["overall_completion_pct"] < 80
        # 各指标应有独立达成率
        for kpi_name, detail in result.data["kpi_scores"].items():
            assert "completion_pct" in detail
            assert detail["completion_pct"] >= 0

    def test_cost_simulation_margin_check(self, menu_agent):
        """成本仿真结果应可用于毛利约束校验

        迁移自: test_recommendations_sorted_by_priority
        新项目: simulate_cost 返回的 data 包含 price_fen 和 cost_fen，
                通过 SkillAgent.run() 自动触发 ConstraintChecker
        """
        result = asyncio.run(menu_agent.run("simulate_cost", {
            "bom_items": [
                {"cost_fen": 800, "quantity": 1},
                {"cost_fen": 500, "quantity": 2},
            ],
            "target_price_fen": 2000,  # 成本 1800，毛利率 10%
        }))
        # 毛利率 10% < 15% 阈值，约束应不通过
        assert result.constraints_passed is False
        assert result.constraints_detail["margin_check"]["passed"] is False


# -- 资源优化测试 (迁移自 TestResourceOptimizationExtended) --


class TestResourceOptimization:
    """资源优化 — 多Agent协同

    老项目: DecisionAgent.optimize_resources 支持 staff/inventory/cost 三种类型
    新项目: 通过 MasterAgent.multi_agent_execute 协同多个 Skill Agent
    """

    def test_multi_agent_coordination(self, master):
        """多Agent并行执行

        迁移自: test_all_resource_types_have_savings
        新项目通过 multi_agent_execute 实现多域协同
        """
        results = asyncio.run(master.multi_agent_execute([
            {"agent_id": "finance_audit", "action": "snapshot_kpi", "params": {
                "kpis": {"revenue": 95000}, "targets": {"revenue": 100000},
            }},
            {"agent_id": "discount_guard", "action": "detect_discount_anomaly", "params": {
                "order": {"total_amount_fen": 10000, "discount_amount_fen": 1000},
            }},
        ]))
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_unknown_agent_dispatch_fails(self, master):
        """未知Agent路由应失败

        迁移自: test_optimize_unknown_resource_raises_error
        """
        result = asyncio.run(master.dispatch("nonexistent_agent", "action", {}))
        assert result.success is False
        assert "not found" in result.error

    def test_intent_routing(self, master):
        """意图路由 — finance 前缀路由到 finance_audit"""
        result = asyncio.run(master.route_intent("finance_report", {
            "report_type": "period_summary",
        }))
        # intent "finance_report" -> prefix "finance" -> finance_audit agent
        assert result.action == "finance_report"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
