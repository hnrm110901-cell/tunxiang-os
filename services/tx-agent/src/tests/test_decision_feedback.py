"""决策反馈服务测试 — 效果计算 + 评分 + 学习上下文 + 统计"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from services.decision_feedback import DecisionFeedbackService

svc = DecisionFeedbackService


class TestRecordExecution:
    """执行记录"""

    def test_record_basic(self):
        record = svc.record_execution("D001", "manager_zhang", {"action": "push_dish"})
        assert record["decision_id"] == "D001"
        assert record["executed_by"] == "manager_zhang"
        assert record["status"] == "executed"
        assert "executed_at" in record


class TestComputeOutcome:
    """效果计算 — 4 种决策类型"""

    def test_menu_push_positive(self):
        """菜品销量增长"""
        result = svc.compute_outcome(
            "menu_push",
            {"sales_count": 100, "revenue": 5000},
            {"sales_count": 140, "revenue": 7000},
        )
        assert result["outcome_score"] >= 80
        assert "+40%" in result["outcome_summary"]
        assert result["metrics_delta"]["sales_count"]["change"] == 40

    def test_menu_push_negative(self):
        """菜品销量下降"""
        result = svc.compute_outcome(
            "menu_push",
            {"sales_count": 100, "revenue": 5000},
            {"sales_count": 70, "revenue": 3500},
        )
        assert result["outcome_score"] < 50
        assert "-30%" in result["outcome_summary"]

    def test_procurement_avoid_shortage(self):
        """采购避免缺货"""
        result = svc.compute_outcome(
            "procurement",
            {"shortage_count": 5, "waste_rate": 0.08},
            {"shortage_count": 0, "waste_rate": 0.05},
        )
        assert result["outcome_score"] >= 80
        assert "缺货减少" in result["outcome_summary"]

    def test_procurement_increased_shortage(self):
        """采购后缺货增加"""
        result = svc.compute_outcome(
            "procurement",
            {"shortage_count": 2, "waste_rate": 0.05},
            {"shortage_count": 5, "waste_rate": 0.07},
        )
        assert result["outcome_score"] < 60
        assert "缺货增加" in result["outcome_summary"]

    def test_staffing_efficiency_up(self):
        """人效提升"""
        result = svc.compute_outcome(
            "staffing",
            {"efficiency": 80, "labor_cost": 10000},
            {"efficiency": 100, "labor_cost": 9500},
        )
        assert result["outcome_score"] >= 80
        assert "+25%" in result["outcome_summary"]
        assert result["metrics_delta"]["efficiency"]["pct"] == 25.0

    def test_staffing_efficiency_down(self):
        """人效下降"""
        result = svc.compute_outcome(
            "staffing",
            {"efficiency": 100, "labor_cost": 10000},
            {"efficiency": 80, "labor_cost": 11000},
        )
        assert result["outcome_score"] < 50

    def test_marketing_conversion_up(self):
        """营销转化率提升"""
        result = svc.compute_outcome(
            "marketing",
            {"reach_rate": 0.3, "conversion_rate": 0.05},
            {"reach_rate": 0.5, "conversion_rate": 0.08},
        )
        assert result["outcome_score"] > 60
        assert "触达率" in result["outcome_summary"]
        assert "转化率" in result["outcome_summary"]

    def test_unknown_type(self):
        """未知决策类型返回基准分"""
        result = svc.compute_outcome("unknown", {}, {})
        assert result["outcome_score"] == 50.0
        assert "未知" in result["outcome_summary"]


class TestEffectivenessScore:
    """综合效果评分"""

    def test_score_from_outcome(self):
        """从 outcome_score 直接取值"""
        score = svc.compute_effectiveness_score({"outcome_score": 85})
        assert score == 85.0

    def test_score_clamped_to_100(self):
        """评分不超过 100"""
        score = svc.compute_effectiveness_score({"outcome_score": 150})
        assert score == 100.0

    def test_score_clamped_to_0(self):
        """评分不低于 0"""
        score = svc.compute_effectiveness_score({"outcome_score": -20})
        assert score == 0.0

    def test_score_from_metrics_delta(self):
        """从 metrics_delta 计算"""
        score = svc.compute_effectiveness_score(
            {
                "metrics_delta": {
                    "sales": {"before": 100, "after": 150, "change": 50, "pct": 50},
                }
            }
        )
        assert score == 100.0  # 50 + 50 = 100

    def test_score_empty_data(self):
        """空数据返回基准分"""
        score = svc.compute_effectiveness_score({})
        assert score == 50.0


class TestLearningContext:
    """学习上下文生成"""

    def test_with_decisions(self):
        """正常生成上下文"""
        decisions = [
            {"title": "主推剁椒鱼头", "outcome_summary": "销量+40%", "outcome_score": 92},
            {"title": "减推外婆鸡", "outcome_summary": "库存消化慢", "outcome_score": 65},
        ]
        context = svc.generate_learning_context(decisions)
        assert "历史决策参考" in context
        assert "主推剁椒鱼头" in context
        assert "销量+40%" in context
        assert "效果分92" in context
        assert "2." in context

    def test_empty_decisions(self):
        """空列表返回提示文本"""
        context = svc.generate_learning_context([])
        assert "暂无" in context

    def test_limit_applied(self):
        """limit 参数生效"""
        decisions = [{"title": f"决策{i}", "outcome_summary": "ok", "outcome_score": 70} for i in range(20)]
        context = svc.generate_learning_context(decisions, limit=3)
        assert "3." in context
        assert "4." not in context


class TestAgentStats:
    """Agent 决策统计"""

    def test_basic_stats(self):
        """基本统计数据"""
        decisions = [
            {"status": "executed", "outcome_score": 90, "title": "A"},
            {"status": "executed", "outcome_score": 80, "title": "B"},
            {"status": "rejected", "outcome_score": 40, "title": "C"},
            {"status": "pending", "title": "D"},
        ]
        stats = svc.get_agent_stats(decisions)
        assert stats["total"] == 4
        assert stats["adopted_count"] == 2
        assert stats["adoption_rate"] == 50.0
        assert stats["avg_score"] == 70.0  # (90+80+40) / 3
        assert len(stats["top_decisions"]) == 3
        assert stats["top_decisions"][0]["outcome_score"] == 90

    def test_empty_decisions(self):
        """空决策列表"""
        stats = svc.get_agent_stats([])
        assert stats["total"] == 0
        assert stats["adoption_rate"] == 0.0
        assert stats["avg_score"] == 0.0

    def test_all_adopted(self):
        """全部采纳"""
        decisions = [
            {"status": "executed", "outcome_score": 85},
            {"status": "adopted", "outcome_score": 90},
        ]
        stats = svc.get_agent_stats(decisions)
        assert stats["adoption_rate"] == 100.0
