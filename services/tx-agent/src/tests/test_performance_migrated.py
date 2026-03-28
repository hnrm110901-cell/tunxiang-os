"""
绩效Agent迁移测试 — 从老项目 packages/agents/performance/tests/test_performance_extended.py 迁移

老项目: PerformanceAgent (KPI计算/提成计算/排名生成/多门店对比)
新项目: 无直接对应的 PerformanceAgent Skill Agent
        FinanceAuditAgent 承载部分 KPI 快照/洞察能力
        ConstraintChecker 承载三条硬约束校验

迁移策略:
- KPI 计算路径 -> FinanceAuditAgent.snapshot_kpi (KPI 达成率/总体达标)
- 绩效报表 -> FinanceAuditAgent.analyze_order_trend (订单/营收趋势)
- 多门店对比 -> MasterAgent 编排多个 FinanceAuditAgent 实例
- 出餐时效指标 -> ServeDispatchAgent.predict_serve_time + ConstraintChecker (出餐时限约束)
- 提成计算等深度绩效能力: 新项目暂无对应，提取业务规则做约束验证
"""

import sys
import os
import asyncio

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult
from agents.constraints import ConstraintChecker
from agents.master import MasterAgent
from agents.skills.finance_audit import FinanceAuditAgent
from agents.skills.serve_dispatch import ServeDispatchAgent
from agents.skills.smart_menu import SmartMenuAgent

TID = "00000000-0000-0000-0000-000000000001"


# -- Fixtures --


@pytest.fixture
def finance_agent():
    return FinanceAuditAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def serve_agent():
    return ServeDispatchAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def menu_agent():
    return SmartMenuAgent(tenant_id=TID, store_id="STORE001")


@pytest.fixture
def constraint_checker():
    return ConstraintChecker()


# -- KPI 计算路径 (迁移自 TestKPICalculationPaths) --


class TestKPIAnalysis:
    """KPI 分析测试 — 对应老项目 TestKPICalculationPaths"""

    def test_kpi_snapshot_full_achievement(self, finance_agent):
        """完全达标的KPI快照

        迁移自: test_store_manager_full_score_range
        老项目: calculate_performance 返回 total_score
        新项目: snapshot_kpi 返回 overall_completion_pct
        """
        result = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 100000, "orders": 200, "satisfaction": 4.8},
            "targets": {"revenue": 100000, "orders": 200, "satisfaction": 4.5},
        }))
        assert result.success is True
        assert result.data["overall_completion_pct"] >= 95

    def test_underperforming_kpis_lower_score(self, finance_agent):
        """表现不佳的指标得分应更低

        迁移自: test_underperforming_score_lower
        """
        result_good = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 100000, "orders": 200},
            "targets": {"revenue": 100000, "orders": 200},
        }))
        result_bad = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 50000, "orders": 80},
            "targets": {"revenue": 100000, "orders": 200},
        }))
        assert result_good.data["overall_completion_pct"] > result_bad.data["overall_completion_pct"]

    def test_serve_time_lower_is_better(self, serve_agent):
        """出餐时间越短越好

        迁移自: test_serve_time_lower_is_better
        老项目: achievement_rate > 1 表示出餐时效优于目标
        新项目: estimated_serve_minutes 越小越好，通过出餐时限约束验证
        """
        # 简单订单应该快速出餐
        result = asyncio.run(serve_agent.execute("predict_serve_time", {
            "dish_count": 2,
            "has_complex_dish": False,
            "kitchen_queue_size": 0,
        }))
        assert result.success is True
        # 2道简单菜，无排队: 5 + 2*2.5 = 10 分钟
        assert result.data["estimated_serve_minutes"] <= 15

    def test_complex_order_longer_serve_time(self, serve_agent):
        """复杂订单出餐时间应更长"""
        result_simple = asyncio.run(serve_agent.execute("predict_serve_time", {
            "dish_count": 3, "has_complex_dish": False, "kitchen_queue_size": 0,
        }))
        result_complex = asyncio.run(serve_agent.execute("predict_serve_time", {
            "dish_count": 3, "has_complex_dish": True, "kitchen_queue_size": 0,
        }))
        assert result_complex.data["estimated_serve_minutes"] > result_simple.data["estimated_serve_minutes"]


# -- 排名与报表 (迁移自 TestRankingGeneration) --


class TestOrderTrendAnalysis:
    """订单趋势分析 — 对应老项目排名/报表功能

    老项目: get_performance_report 汇总多岗位绩效和排名
    新项目: analyze_order_trend 分析订单量和营收趋势
    """

    def test_upward_trend_detected(self, finance_agent):
        """上升趋势检测

        迁移自: test_multi_role_report_ranking (报表汇总能力)
        """
        result = asyncio.run(finance_agent.execute("analyze_order_trend", {
            "daily_orders": [100, 110, 120, 130, 140],
            "daily_revenue_fen": [500000, 550000, 600000, 650000, 700000],
        }))
        assert result.success is True
        assert result.data["order_trend"] == "up"
        assert result.data["avg_ticket_yuan"] > 0

    def test_downward_trend_detected(self, finance_agent):
        """下降趋势检测"""
        result = asyncio.run(finance_agent.execute("analyze_order_trend", {
            "daily_orders": [200, 180, 160, 140, 120],
            "daily_revenue_fen": [1000000, 900000, 800000, 700000, 600000],
        }))
        assert result.success is True
        assert result.data["order_trend"] == "down"

    def test_forecast_orders(self, finance_agent):
        """订单预测

        迁移自: test_single_role_report (单岗位报表 -> 单维度预测)
        """
        result = asyncio.run(finance_agent.execute("forecast_orders", {
            "daily_orders": [150, 140, 160, 180, 200, 190, 170,
                             155, 145, 165, 175, 195, 185, 175],
            "days_ahead": 7,
        }))
        assert result.success is True
        assert len(result.data["daily_forecast"]) == 7
        assert result.data["total_forecast"] > 0


# -- 多门店对比 (迁移自 TestMultiStoreComparison) --


class TestMultiStoreComparison:
    """多门店对比测试"""

    def test_different_stores_independent_analysis(self):
        """不同门店的分析应独立

        迁移自: test_different_stores_same_role
        """
        agent_a = FinanceAuditAgent(tenant_id=TID, store_id="STORE_A")
        agent_b = FinanceAuditAgent(tenant_id=TID, store_id="STORE_B")

        result_a = asyncio.run(agent_a.execute("snapshot_kpi", {
            "kpis": {"revenue": 100000}, "targets": {"revenue": 100000},
        }))
        result_b = asyncio.run(agent_b.execute("snapshot_kpi", {
            "kpis": {"revenue": 50000}, "targets": {"revenue": 100000},
        }))

        assert result_a.success is True
        assert result_b.success is True
        assert result_a.data["overall_completion_pct"] > result_b.data["overall_completion_pct"]

    def test_store_id_preserved(self):
        """Agent 实例的 store_id 应保留

        迁移自: test_store_id_preserved_in_report
        """
        agent = FinanceAuditAgent(tenant_id=TID, store_id="STORE_X")
        assert agent.store_id == "STORE_X"

    def test_multi_store_via_master(self):
        """通过 MasterAgent 协调多门店分析

        迁移自: test_cross_store_commission_rule_returns_none
        (老项目跨门店汇总需总部，新项目通过 MasterAgent 编排)
        """
        master = MasterAgent(tenant_id=TID, store_id="STORE001")
        master.register(FinanceAuditAgent(tenant_id=TID, store_id="STORE001"))
        master.register(SmartMenuAgent(tenant_id=TID, store_id="STORE001"))

        results = asyncio.run(master.multi_agent_execute([
            {"agent_id": "finance_audit", "action": "snapshot_kpi", "params": {
                "kpis": {"revenue": 95000}, "targets": {"revenue": 100000},
            }},
            {"agent_id": "smart_menu", "action": "classify_quadrant", "params": {
                "total_sales": 200, "margin_rate": 0.5, "avg_sales": 100, "avg_margin": 0.3,
            }},
        ]))
        assert len(results) == 2
        assert all(r.success for r in results)


# -- 边界场景 (迁移自 TestEdgeCases) --


class TestEdgeCases:
    """边界场景测试"""

    def test_confidence_range(self, finance_agent):
        """置信度应在合理范围

        迁移自: test_extreme_high_value
        """
        result = asyncio.run(finance_agent.execute("snapshot_kpi", {
            "kpis": {"revenue": 999999},
            "targets": {"revenue": 100},
        }))
        assert 0 <= result.confidence <= 1.0

    def test_all_agent_actions_no_crash(self, serve_agent):
        """所有支持的 action 都不应崩溃

        迁移自: test_all_roles_commission_no_crash
        """
        actions_with_minimal_params = {
            "predict_serve_time": {"dish_count": 1},
            "detect_order_anomaly": {"order": {}},
        }
        for action, params in actions_with_minimal_params.items():
            result = asyncio.run(serve_agent.execute(action, params))
            assert result.success is True, f"Action {action} 不应崩溃"

    def test_empty_traffic_data_fails_gracefully(self, serve_agent):
        """空客流数据应优雅失败"""
        result = asyncio.run(serve_agent.execute("analyze_traffic", {
            "hourly_customers": [1, 2, 3],  # 少于12小时
        }))
        assert result.success is False

    def test_workload_balance(self, serve_agent):
        """工作量平衡检测"""
        result = asyncio.run(serve_agent.execute("balance_workload", {
            "staff_loads": [
                {"name": "张三", "current_orders": 15},
                {"name": "李四", "current_orders": 3},
                {"name": "王五", "current_orders": 8},
            ],
        }))
        assert result.success is True
        assert result.data["balance_score"] >= 0
        assert len(result.data["overloaded"]) > 0  # 张三超载
        assert len(result.data["underloaded"]) > 0  # 李四空闲

    def test_dish_review_verdict(self, menu_agent):
        """菜品复盘四种结论

        迁移自: 绩效评估的评级逻辑
        """
        # keep: 高毛利+高销量+低退菜+低差评
        result = asyncio.run(menu_agent.execute("run_dish_review", {
            "total_sales": 200, "return_count": 2, "bad_review_count": 5,
            "margin_rate": 0.35, "category_avg_sales": 100,
        }))
        assert result.data["verdict"] == "keep"

        # retire: 低销量
        result = asyncio.run(menu_agent.execute("run_dish_review", {
            "total_sales": 30, "return_count": 5, "bad_review_count": 3,
            "margin_rate": 0.15, "category_avg_sales": 100,
        }))
        assert result.data["verdict"] == "retire"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
