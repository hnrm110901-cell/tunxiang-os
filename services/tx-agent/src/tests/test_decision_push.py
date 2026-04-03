"""决策推送纯函数测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.decision_push import (
    MAX_DESC_CHARS,
    format_evening_recap,
    format_morning_card,
    format_noon_anomaly,
    format_prebattle,
    should_push_evening,
    should_push_noon,
    should_push_prebattle,
)

SAMPLE_DECISIONS = [
    {"title": "减少鲈鱼采购30%", "action": "联系供应商调整下周采购量", "expected_saving_yuan": 1200, "confidence": 0.85, "difficulty": "easy", "source": "inventory"},
    {"title": "下架低毛利菜品3道", "action": "从菜单移除瘦狗象限菜品", "expected_saving_yuan": 650, "confidence": 0.72, "difficulty": "medium", "source": "menu"},
    {"title": "周末增加2名服务员", "action": "安排临时工周六日上岗", "expected_saving_yuan": 800, "confidence": 0.78, "difficulty": "hard", "source": "schedule", "urgency_hours": 3},
]


class TestMorningCard:
    def test_formats_top3(self):
        result = format_morning_card(SAMPLE_DECISIONS)
        assert "减少鲈鱼" in result
        assert "¥1200" in result
        assert "置信度85%" in result

    def test_empty(self):
        result = format_morning_card([])
        assert "暂无" in result

    def test_within_limit(self):
        assert len(format_morning_card(SAMPLE_DECISIONS)) <= MAX_DESC_CHARS


class TestNoonAnomaly:
    def test_critical_waste(self):
        result = format_noon_anomaly(
            {"waste_rate_pct": 6.5, "waste_cost_yuan": 850, "waste_rate_status": "critical",
             "top5": [{"item_name": "鲈鱼", "waste_cost_yuan": 320, "action": "调整备餐量"}]},
            SAMPLE_DECISIONS,
        )
        assert "🔴" in result
        assert "鲈鱼" in result

    def test_ok_waste(self):
        result = format_noon_anomaly(
            {"waste_rate_pct": 2.0, "waste_cost_yuan": 200, "waste_rate_status": "ok", "top5": []},
            [],
        )
        assert "✅" in result


class TestPrebattle:
    def test_has_inventory(self):
        result = format_prebattle(SAMPLE_DECISIONS, "芙蓉路店")
        assert "芙蓉路店" in result
        assert "库存决策" in result
        assert "减少鲈鱼" in result

    def test_no_decisions(self):
        result = format_prebattle([], "A店")
        assert "均正常" in result


class TestEveningRecap:
    def test_with_pending(self):
        result = format_evening_recap(SAMPLE_DECISIONS, pending_count=3)
        assert "3 条决策待审批" in result
        assert "¥2650" in result  # 1200+650+800

    def test_nothing_to_push(self):
        result = format_evening_recap([], 0)
        assert "经营正常" in result


class TestPushDecisions:
    def test_noon_push_on_warning(self):
        assert should_push_noon("warning", False) is True

    def test_noon_no_push_ok(self):
        assert should_push_noon("ok", False) is False

    def test_prebattle_with_inventory(self):
        assert should_push_prebattle(SAMPLE_DECISIONS) is True

    def test_prebattle_no_urgency(self):
        assert should_push_prebattle([{"source": "menu", "urgency_hours": 24}]) is False

    def test_evening_with_pending(self):
        assert should_push_evening(3, False) is True

    def test_evening_nothing(self):
        assert should_push_evening(0, False) is False
