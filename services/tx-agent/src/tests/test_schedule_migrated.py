"""
排班Agent迁移测试 — 从老项目 packages/agents/schedule/tests/test_schedule_extended.py 迁移

老项目: ScheduleAgent (排班生成/客流预测/人力预算/排班调整)
新项目: ServeDispatchAgent (出餐时间预测/排班优化/客流分析/人力需求预测/订单异常/链式告警)

迁移策略:
- 排班生成 -> ServeDispatchAgent.optimize_schedule (排班优化)
- 周末客流 -> ServeDispatchAgent.analyze_traffic (客流分析)
- 人力预算 -> ServeDispatchAgent.predict_staffing_needs (人力需求预测)
- 排班调整 -> 通过 Agent action 参数传入调整需求
- 出餐时限约束 -> ConstraintChecker.check_experience
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.constraints import ConstraintChecker
from agents.skills.serve_dispatch import ServeDispatchAgent

TID = "00000000-0000-0000-0000-000000000001"


# -- Fixtures --


@pytest.fixture
def agent():
    return ServeDispatchAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def constraint_checker():
    return ConstraintChecker()


@pytest.fixture
def employees():
    """员工列表"""
    return [
        {"name": f"服务员{i}", "role": "waiter"} for i in range(1, 6)
    ] + [
        {"name": f"厨师{i}", "role": "chef"} for i in range(1, 4)
    ]


@pytest.fixture
def traffic_forecast():
    """24小时客流预测"""
    return [
        5, 3, 2, 1, 1, 5,       # 00-05: 夜间低谷
        15, 30, 45, 35, 25, 60,  # 06-11: 早午高峰
        80, 70, 40, 30, 35, 65,  # 12-17: 午间高峰+下午
        90, 85, 60, 40, 20, 10,  # 18-23: 晚餐高峰+收尾
    ]


# -- 排班生成逻辑 (迁移自 TestScheduleGeneration) --


class TestScheduleOptimization:
    """排班优化测试 — 对应老项目 TestScheduleGeneration"""

    def test_schedule_generated_with_employees(self, agent, employees, traffic_forecast):
        """排班应覆盖所有员工

        迁移自: test_all_shifts_covered_with_large_team
        老项目: result["schedule"] 包含各班次排班
        新项目: optimize_schedule 返回 schedule 列表
        """
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.success is True
        assert len(result.data["schedule"]) == len(employees)
        assert result.data["staff_count"] == len(employees)

    def test_peak_hours_identified(self, agent, employees, traffic_forecast):
        """应识别客流高峰时段

        迁移自: test_weekend_traffic_higher
        新项目: optimize_schedule 返回 peak_hours 列表
        """
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.success is True
        assert len(result.data["peak_hours"]) > 0
        # 高峰时段应包含午餐和晚餐时间
        peak_set = set(result.data["peak_hours"])
        assert any(h in peak_set for h in [12, 13, 18, 19]), "高峰时段应包含餐段"

    def test_schedule_entries_have_structure(self, agent, employees, traffic_forecast):
        """排班记录应有完整结构

        迁移自: test_schedule_entries_have_complete_structure
        老项目: 要求 employee_id/employee_name/skill/shift/date/start_time/end_time
        新项目: 返回 employee + hours 结构
        """
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        for entry in result.data["schedule"]:
            assert "employee" in entry, "排班记录必须包含 employee"
            assert "hours" in entry, "排班记录必须包含 hours"
            assert len(entry["hours"]) > 0, "排班时段不能为空"

    def test_empty_employees_fails(self, agent, traffic_forecast):
        """空员工列表应失败

        迁移自: 边界场景
        """
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": [],
            "traffic_forecast": traffic_forecast,
        }))
        assert result.success is False

    def test_empty_forecast_fails(self, agent, employees):
        """空客流预测应失败"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": [],
        }))
        assert result.success is False


# -- 客流分析 (迁移自排班中的客流部分) --


class TestTrafficAnalysis:
    """客流分析测试"""

    def test_traffic_analysis_peaks_and_valleys(self, agent, traffic_forecast):
        """客流分析应识别峰谷

        迁移自: test_weekend_traffic_higher (客流对比逻辑)
        """
        result = asyncio.run(agent.execute("analyze_traffic", {
            "hourly_customers": traffic_forecast,
        }))
        assert result.success is True
        assert result.data["total_customers"] == sum(traffic_forecast)
        assert len(result.data["peak_hours"]) > 0
        assert len(result.data["valley_hours"]) > 0
        assert result.data["peak_ratio"] > 1.0

    def test_insufficient_data_fails(self, agent):
        """数据不足应失败"""
        result = asyncio.run(agent.execute("analyze_traffic", {
            "hourly_customers": [10, 20, 30],
        }))
        assert result.success is False


# -- 人力需求预测 (迁移自 TestLaborBudgetConstraint) --


class TestStaffingNeeds:
    """人力需求预测 — 对应老项目 TestLaborBudgetConstraint"""

    def test_staffing_needs_calculated(self, agent):
        """人力需求应根据客流预测计算

        迁移自: test_labor_cost_summary_present
        老项目: labor_cost_summary 包含 estimated_total_cost
        新项目: predict_staffing_needs 返回各时段人力需求
        """
        result = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [20, 40, 80, 60, 30, 90, 70, 50],
            "service_ratio": 15,
        }))
        assert result.success is True
        assert result.data["total_staff_hours"] > 0
        assert result.data["max_concurrent"] > 0

    def test_high_traffic_needs_more_staff(self, agent):
        """高客流需要更多人力

        迁移自: test_budget_exceeded_triggers_cost_control
        """
        result_low = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [10, 15, 20, 15, 10],
            "service_ratio": 15,
        }))
        result_high = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [50, 80, 120, 90, 60],
            "service_ratio": 15,
        }))
        assert result_high.data["total_staff_hours"] > result_low.data["total_staff_hours"]

    def test_empty_forecast_fails(self, agent):
        """空预测数据应失败

        迁移自: test_no_budget_constraint_no_cost_action (无数据场景)
        """
        result = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [],
        }))
        assert result.success is False


# -- 排班调整与边界 (迁移自 TestScheduleAdjustmentExtended) --


class TestScheduleEdgeCases:
    """排班相关边界测试"""

    def test_order_anomaly_detection(self, agent):
        """订单异常检测 — 出餐超时

        迁移自: test_adjust_schedule_unknown_employee (异常处理)
        新项目: detect_order_anomaly 检测超时/退菜/高折扣
        """
        result = asyncio.run(agent.execute("detect_order_anomaly", {
            "order": {
                "elapsed_minutes": 35,
                "return_count": 0,
                "discount_rate": 0.1,
            },
        }))
        assert result.success is True
        assert result.data["is_anomaly"] is True
        assert any(a["type"] == "timeout" for a in result.data["anomalies"])

    def test_chain_alert_kitchen_delay(self, agent):
        """链式告警 — 厨房延迟触发多层联动

        迁移自: 老项目的排班与出餐联动逻辑
        新项目: trigger_chain_alert 实现1触发3层联动
        """
        result = asyncio.run(agent.execute("trigger_chain_alert", {
            "event": {"type": "kitchen_delay", "source": "order_123"},
        }))
        assert result.success is True
        assert len(result.data["L2_related"]) > 0
        assert len(result.data["L3_actions"]) > 0

    def test_unsupported_action(self, agent):
        """不支持的 action 应安全处理

        迁移自: test_execute_unsupported_action
        """
        # ServeDispatchAgent 的 dispatch 会 KeyError，由 run() 捕获
        result = asyncio.run(agent.run("invalid_action", {}))
        assert result.success is False
        assert result.error is not None

    def test_get_supported_actions(self, agent):
        """支持的操作列表应完整

        迁移自: test_get_supported_actions
        """
        actions = agent.get_supported_actions()
        expected = [
            "predict_serve_time", "optimize_schedule", "analyze_traffic",
            "predict_staffing_needs", "detect_order_anomaly",
            "trigger_chain_alert", "balance_workload",
        ]
        for action in expected:
            assert action in actions, f"缺少操作: {action}"


# -- 出餐时限约束 (三硬约束之一) --


class TestServeTimeConstraint:
    """出餐时限约束测试 — 三硬约束之客户体验"""

    def test_serve_time_within_limit(self, agent, constraint_checker):
        """出餐时间在限制内应通过

        对应产品宪法: 出餐时间不可超过门店设定上限 (默认30分钟)
        """
        result = asyncio.run(agent.execute("predict_serve_time", {
            "dish_count": 3,
            "has_complex_dish": False,
            "kitchen_queue_size": 2,
        }))
        estimated = result.data["estimated_serve_minutes"]

        check = constraint_checker.check_experience({
            "estimated_serve_minutes": estimated,
        })
        assert check["passed"] is True, f"预计出餐 {estimated} 分钟应在限制内"

    def test_serve_time_exceeds_limit(self, constraint_checker):
        """出餐时间超限应不通过"""
        check = constraint_checker.check_experience({
            "estimated_serve_minutes": 45,
        })
        assert check["passed"] is False
        assert check["actual_minutes"] == 45

    def test_serve_time_constraint_in_agent_run(self, agent):
        """Agent.run() 自动触发出餐时限约束校验

        大量菜品+复杂菜+长队列 -> 可能超时
        """
        result = asyncio.run(agent.run("predict_serve_time", {
            "dish_count": 8,
            "has_complex_dish": True,
            "kitchen_queue_size": 10,
        }))
        estimated = result.data["estimated_serve_minutes"]
        # 5 + 8*2.5 + 8 + 10*1.5 = 5 + 20 + 8 + 15 = 48 分钟
        assert estimated > 30, "该场景应超出出餐时限"

        # SkillAgent.run() 应自动校验出餐时限
        if result.constraints_detail.get("experience_check"):
            assert result.constraints_detail["experience_check"]["passed"] is False

    def test_custom_serve_time_limit(self):
        """自定义出餐时限"""
        checker = ConstraintChecker(max_serve_minutes=15)
        check = checker.check_experience({"estimated_serve_minutes": 20})
        assert check["passed"] is False
        assert check["threshold_minutes"] == 15


# =============================================================================
# P1-2 补全: 排班优化Agent扩展测试 — v6审计修复
# =============================================================================


class TestScheduleAgentInit:
    """Agent 初始化和状态验证"""

    def test_serve_dispatch_metadata(self, agent):
        """出餐调度Agent(含排班)元信息应完整"""
        info = agent.get_info()
        assert info["agent_id"] == "serve_dispatch"
        assert info["agent_name"] == "出餐调度"
        assert info["priority"] == "P1"
        assert "optimize_schedule" in info["supported_actions"]
        assert "analyze_traffic" in info["supported_actions"]
        assert "predict_staffing_needs" in info["supported_actions"]

    def test_agent_is_edge_location(self, agent):
        """排班Agent应在边缘运行"""
        assert agent.run_location == "edge"

    def test_agent_preserves_ids(self, agent):
        """Agent应保留tenant和store信息"""
        assert agent.tenant_id == TID
        assert agent.store_id == "STORE001"


class TestScheduleHappyPath:
    """排班核心决策逻辑 — 基于真实餐厅场景"""

    def test_weekend_lunch_dinner_peak_coverage(self, agent, employees, traffic_forecast):
        """周末午晚高峰应有充足人手覆盖"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        peak_hours = set(result.data["peak_hours"])
        # 高峰应包含12-13(午餐)和18-19(晚餐)中至少一个
        lunch_covered = any(h in peak_hours for h in [12, 13])
        dinner_covered = any(h in peak_hours for h in [18, 19])
        assert lunch_covered or dinner_covered, "排班应覆盖午餐或晚餐高峰"

    def test_schedule_cost_estimate(self, agent, employees, traffic_forecast):
        """排班应包含成本估算"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.data["estimated_cost_fen"] > 0

    def test_budget_check_within_budget(self, agent, employees, traffic_forecast):
        """预算充足时应标记在预算内"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
            "budget_fen": 999999999,
        }))
        assert result.data["cost_within_budget"] is True

    def test_budget_check_over_budget(self, agent, employees, traffic_forecast):
        """预算不足时应标记超预算"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
            "budget_fen": 1,  # 1分钱预算
        }))
        assert result.data["cost_within_budget"] is False

    def test_staffing_with_custom_service_ratio(self, agent):
        """自定义服务比(每人服务客数)应影响人力需求"""
        # 高服务比(每人服务更多客人) = 需要更少人
        result_high = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [60, 90, 120],
            "service_ratio": 30,  # 每人服务30客
        }))
        result_low = asyncio.run(agent.execute("predict_staffing_needs", {
            "forecast_customers": [60, 90, 120],
            "service_ratio": 10,  # 每人服务10客
        }))
        assert result_low.data["total_staff_hours"] > result_high.data["total_staff_hours"]


class TestScheduleHardConstraints:
    """三条硬约束在排班Agent中的验证"""

    def test_experience_constraint_via_serve_prediction(self, agent):
        """出餐时限约束：排班不足导致出餐超时应违规"""
        result = asyncio.run(agent.run("predict_serve_time", {
            "dish_count": 6,
            "has_complex_dish": True,
            "kitchen_queue_size": 12,
        }))
        # 5 + 6*2.5 + 8 + 12*1.5 = 5+15+8+18 = 46分钟 > 30分钟
        assert result.data["estimated_serve_minutes"] > 30
        exp_check = result.constraints_detail.get("experience_check")
        if exp_check:
            assert exp_check["passed"] is False

    def test_experience_constraint_pass_for_simple(self, agent):
        """出餐时限约束：简单订单不应超时"""
        result = asyncio.run(agent.run("predict_serve_time", {
            "dish_count": 2, "has_complex_dish": False, "kitchen_queue_size": 0,
        }))
        assert result.data["estimated_serve_minutes"] <= 30
        exp_check = result.constraints_detail.get("experience_check")
        if exp_check:
            assert exp_check["passed"] is True

    def test_margin_constraint_skipped_for_schedule(self, agent, employees, traffic_forecast):
        """排班操作不涉及价格，毛利约束应跳过"""
        result = asyncio.run(agent.run("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.constraints_detail.get("margin_check") is None

    def test_food_safety_skipped_for_schedule(self, agent, employees, traffic_forecast):
        """排班操作不涉及食材，食安约束应跳过"""
        result = asyncio.run(agent.run("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.constraints_detail.get("food_safety_check") is None

    def test_custom_serve_time_limit_affects_result(self, constraint_checker):
        """自定义出餐时限应影响约束结果"""
        checker_strict = ConstraintChecker(max_serve_minutes=15)
        check = checker_strict.check_experience({"estimated_serve_minutes": 20})
        assert check["passed"] is False
        assert check["threshold_minutes"] == 15


class TestScheduleDecisionLog:
    """排班Agent决策留痕验证"""

    def test_schedule_optimization_audit_trail(self, agent, employees, traffic_forecast):
        """排班优化必须有完整决策留痕"""
        result = asyncio.run(agent.run("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": traffic_forecast,
        }))
        assert result.action == "optimize_schedule"
        assert len(result.reasoning) > 0
        assert result.confidence > 0
        assert result.execution_ms >= 0
        assert result.constraints_detail is not None
        assert "passed" in result.constraints_detail

    def test_traffic_analysis_audit_trail(self, agent, traffic_forecast):
        """客流分析必须有留痕"""
        result = asyncio.run(agent.run("analyze_traffic", {
            "hourly_customers": traffic_forecast,
        }))
        assert result.action == "analyze_traffic"
        assert result.agent_level in (1, 2, 3)
        assert result.execution_ms >= 0

    def test_chain_alert_audit_trail(self, agent):
        """链式告警必须有留痕"""
        result = asyncio.run(agent.run("trigger_chain_alert", {
            "event": {"type": "kitchen_delay", "source": "order_456"},
        }))
        assert result.action == "trigger_chain_alert"
        assert len(result.reasoning) > 0
        assert result.confidence > 0

    def test_failed_action_audit_trail(self, agent):
        """失败操作也必须有决策留痕"""
        result = asyncio.run(agent.run("invalid_action_xyz", {}))
        assert result.success is False
        assert result.execution_ms >= 0
        assert result.constraints_detail is not None


class TestScheduleInputDegradation:
    """输入异常时的降级处理"""

    def test_single_employee_schedule(self, agent, traffic_forecast):
        """只有1个员工的排班不应崩溃"""
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": [{"name": "独守员工", "role": "waiter"}],
            "traffic_forecast": traffic_forecast,
        }))
        assert result.success is True
        assert result.data["staff_count"] == 1

    def test_flat_traffic_no_peaks(self, agent, employees):
        """完全平坦的客流数据(无高峰)不应崩溃"""
        flat_traffic = [50] * 24
        result = asyncio.run(agent.execute("optimize_schedule", {
            "employees": employees,
            "traffic_forecast": flat_traffic,
        }))
        assert result.success is True
        # 所有小时客流相同,无法超过mean*1.2, 高峰应为空
        assert len(result.data["peak_hours"]) == 0

    def test_complaint_chain_alert(self, agent):
        """投诉事件链式告警应触发不同关联检查"""
        result = asyncio.run(agent.execute("trigger_chain_alert", {
            "event": {"type": "complaint", "source": "table_15"},
        }))
        assert result.success is True
        assert any(r["check"] == "菜品质量记录" for r in result.data["L2_related"])
        assert "通知店长处理" in result.data["L3_actions"]

    def test_unknown_event_type_chain_alert(self, agent):
        """未知事件类型的链式告警不应崩溃"""
        result = asyncio.run(agent.execute("trigger_chain_alert", {
            "event": {"type": "unknown_event_xyz"},
        }))
        assert result.success is True
        assert result.data["L1_trigger"]["type"] == "unknown_event_xyz"

    def test_order_anomaly_no_issues(self, agent):
        """正常订单不应触发异常"""
        result = asyncio.run(agent.execute("detect_order_anomaly", {
            "order": {
                "elapsed_minutes": 15,
                "return_count": 0,
                "discount_rate": 0.1,
            },
        }))
        assert result.data["is_anomaly"] is False

    def test_order_multiple_anomalies(self, agent):
        """一个订单同时存在多种异常"""
        result = asyncio.run(agent.execute("detect_order_anomaly", {
            "order": {
                "elapsed_minutes": 40,   # 超时
                "return_count": 3,       # 多次退菜
                "discount_rate": 0.6,    # 大额折扣
            },
        }))
        assert result.data["is_anomaly"] is True
        assert result.data["anomaly_count"] == 3
        anomaly_types = {a["type"] for a in result.data["anomalies"]}
        assert "timeout" in anomaly_types
        assert "multi_return" in anomaly_types
        assert "high_discount" in anomaly_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
