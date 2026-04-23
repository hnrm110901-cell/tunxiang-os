"""经营叙事引擎纯函数测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.narrative_engine import (
    BRIEF_MAX_CHARS,
    build_action,
    build_overview,
    compose_brief,
    detect_anomalies,
)


class TestBuildOverview:
    def test_basic(self):
        result = build_overview(
            "芙蓉路店",
            {"revenue_yuan": 8560, "actual_cost_pct": 32.5, "cost_rate_label": "正常"},
            {"approved": 2, "total": 3},
        )
        assert "芙蓉路店" in result
        assert "8,560" in result
        assert "32.5%" in result
        assert "2/3" in result

    def test_no_decisions(self):
        result = build_overview(
            "A店", {"revenue_yuan": 5000, "actual_cost_pct": 30, "cost_rate_label": "正常"}, {"total": 0}
        )
        assert "决策" not in result


class TestDetectAnomalies:
    def test_critical_cost(self):
        result = detect_anomalies(
            {"cost_rate_status": "critical", "actual_cost_pct": 42.0},
            [],
            0,
            [],
        )
        assert len(result) >= 1
        assert "严重超标" in result[0]

    def test_warning_cost(self):
        result = detect_anomalies(
            {"cost_rate_status": "warning", "actual_cost_pct": 35.0},
            [],
            0,
            [],
        )
        assert any("偏高" in a for a in result)

    def test_waste_top1(self):
        result = detect_anomalies(
            {"cost_rate_status": "ok"},
            [{"item_name": "鲈鱼", "waste_cost_yuan": 320, "action": "检查供应商"}],
            0,
            [],
        )
        assert any("鲈鱼" in a for a in result)

    def test_pending_decisions(self):
        result = detect_anomalies(
            {"cost_rate_status": "ok"},
            [],
            3,
            [{"expected_saving_yuan": 500}],
        )
        assert any("3条决策" in a for a in result)

    def test_max_3_anomalies(self):
        result = detect_anomalies(
            {"cost_rate_status": "critical", "actual_cost_pct": 45},
            [{"item_name": "X", "waste_cost_yuan": 100, "action": "fix"}],
            5,
            [{"expected_saving_yuan": 200}],
        )
        assert len(result) <= 3

    def test_no_anomalies(self):
        result = detect_anomalies({"cost_rate_status": "ok"}, [], 0, [])
        assert len(result) == 0


class TestBuildAction:
    def test_from_decision(self):
        result = build_action([{"action": "明天减少鲈鱼采购30%"}], {})
        assert "明天减少" in result

    def test_critical_fallback(self):
        result = build_action([], {"cost_rate_status": "critical"})
        assert "核查超标食材" in result

    def test_warning_fallback(self):
        result = build_action([], {"cost_rate_status": "warning"})
        assert "备料量" in result

    def test_default(self):
        result = build_action([], {"cost_rate_status": "ok"})
        assert "维持当前" in result


class TestComposeBrief:
    def test_under_200_chars(self):
        result = compose_brief(
            "芙蓉路店",
            {"revenue_yuan": 8560, "actual_cost_pct": 32, "cost_rate_label": "正常", "cost_rate_status": "ok"},
            {"approved": 2, "total": 3},
            [],
        )
        assert len(result) <= BRIEF_MAX_CHARS

    def test_truncation(self):
        """超长内容应被截断到200字"""
        result = compose_brief(
            "一个非常长名字的门店名称" * 3,
            {"revenue_yuan": 999999, "actual_cost_pct": 45, "cost_rate_label": "严重", "cost_rate_status": "critical"},
            {"approved": 0, "total": 5},
            [{"item_name": "很长的食材名" * 5, "waste_cost_yuan": 999, "action": "很长的建议" * 5}],
            pending_count=10,
            top_decisions=[{"expected_saving_yuan": 5000, "action": "很长的决策建议" * 5}],
        )
        assert len(result) <= BRIEF_MAX_CHARS

    def test_contains_all_parts(self):
        result = compose_brief(
            "A店",
            {"revenue_yuan": 5000, "actual_cost_pct": 36, "cost_rate_label": "偏高", "cost_rate_status": "warning"},
            {"total": 0},
            [{"item_name": "鱼", "waste_cost_yuan": 200, "action": "检查"}],
        )
        assert "A店" in result
        assert "5,000" in result
        assert "鱼" in result
        assert "✅" in result
