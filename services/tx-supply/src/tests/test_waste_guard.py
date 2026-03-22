"""损耗监控纯函数测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.waste_guard_service import (
    action_for_causes, compute_waste_rate, classify_waste_status,
    compute_waste_change, build_top5_item, build_waste_rate_summary,
)


class TestActionForCauses:
    def test_staff_error(self):
        result = action_for_causes([{"root_cause": "staff_error"}])
        assert "培训" in result

    def test_over_prep(self):
        result = action_for_causes([{"root_cause": "over_prep"}])
        assert "备餐量" in result

    def test_spoilage(self):
        result = action_for_causes([{"root_cause": "spoilage"}])
        assert "采购周期" in result

    def test_empty_causes(self):
        result = action_for_causes([])
        assert "追踪" in result

    def test_unknown_cause(self):
        result = action_for_causes([{"root_cause": "aliens"}])
        assert "追踪" in result


class TestComputeWasteRate:
    def test_normal(self):
        rate = compute_waste_rate(3000, 100000)
        assert rate == 3.0

    def test_zero_revenue(self):
        assert compute_waste_rate(3000, 0) is None

    def test_high(self):
        rate = compute_waste_rate(8000, 100000)
        assert rate == 8.0


class TestClassifyWasteStatus:
    def test_ok(self):
        assert classify_waste_status(2.5) == "ok"

    def test_warning(self):
        assert classify_waste_status(3.5) == "warning"

    def test_critical(self):
        assert classify_waste_status(6.0) == "critical"

    def test_none(self):
        assert classify_waste_status(None) == "ok"

    def test_boundary_3(self):
        assert classify_waste_status(3.0) == "warning"

    def test_boundary_5(self):
        assert classify_waste_status(5.0) == "critical"


class TestComputeWasteChange:
    def test_increase(self):
        result = compute_waste_change(5000, 3000)
        assert result["direction"] == "up"
        assert result["change_fen"] == 2000
        assert result["change_yuan"] == 20.0

    def test_decrease(self):
        result = compute_waste_change(2000, 5000)
        assert result["direction"] == "down"
        assert result["change_pct"] == -60.0

    def test_no_change(self):
        result = compute_waste_change(3000, 3000)
        assert result["direction"] == "flat"

    def test_prev_zero(self):
        result = compute_waste_change(3000, 0)
        assert result["change_pct"] is None


class TestBuildTop5Item:
    def test_basic(self):
        item = build_top5_item(
            rank=1,
            item_name="鲈鱼",
            waste_cost_fen=32000,
            waste_qty=5.0,
            total_waste_fen=100000,
            root_causes=[{"root_cause": "over_prep", "event_count": 3}],
        )
        assert item["rank"] == 1
        assert item["waste_cost_yuan"] == 320.0
        assert item["cost_share_pct"] == 32.0
        assert "备餐量" in item["action"]

    def test_zero_total(self):
        item = build_top5_item(1, "X", 1000, 1.0, 0, [])
        assert item["cost_share_pct"] == 0.0


class TestBuildWasteRateSummary:
    def test_complete(self):
        result = build_waste_rate_summary(
            waste_fen=3500,
            revenue_fen=100000,
            prev_waste_fen=3000,
            start_date="2026-03-15",
            end_date="2026-03-22",
        )
        assert result["waste_rate_pct"] == 3.5
        assert result["waste_rate_status"] == "warning"
        assert result["waste_cost_yuan"] == 35.0
        assert result["vs_previous"]["direction"] == "up"
