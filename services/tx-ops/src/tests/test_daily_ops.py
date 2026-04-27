"""日清日结服务测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.daily_ops_service import (
    NODE_DEFINITIONS,
    compute_flow_progress,
    compute_node_check_result,
    get_flow_timeline,
    get_node_definition,
)


class TestNodeDefinitions:
    def test_all_8_nodes_defined(self):
        for i in range(1, 9):
            assert f"E{i}" in NODE_DEFINITIONS

    def test_e1_has_required_checks(self):
        defn = get_node_definition("E1")
        assert defn["name"] == "开店准备"
        required = [c for c in defn["check_items"] if c["required"]]
        assert len(required) >= 3

    def test_unknown_node(self):
        assert get_node_definition("E99") == {}


class TestFlowProgress:
    def test_not_started(self):
        statuses = {f"E{i}": "pending" for i in range(1, 9)}
        result = compute_flow_progress(statuses)
        assert result["completed"] == 0
        assert result["status"] == "not_started"
        assert result["current_node"] == "E1"

    def test_in_progress(self):
        statuses = {
            "E1": "completed",
            "E2": "completed",
            "E3": "in_progress",
            "E4": "pending",
            "E5": "pending",
            "E6": "pending",
            "E7": "pending",
            "E8": "pending",
        }
        result = compute_flow_progress(statuses)
        assert result["completed"] == 2
        assert result["pct"] == 25.0
        assert result["current_node"] == "E3"

    def test_completed(self):
        statuses = {f"E{i}": "completed" for i in range(1, 9)}
        result = compute_flow_progress(statuses)
        assert result["completed"] == 8
        assert result["status"] == "completed"

    def test_skipped_counts(self):
        statuses = {
            "E1": "completed",
            "E2": "skipped",
            "E3": "completed",
            "E4": "pending",
            "E5": "pending",
            "E6": "pending",
            "E7": "pending",
            "E8": "pending",
        }
        result = compute_flow_progress(statuses)
        assert result["completed"] == 3  # skipped 也算


class TestCheckResult:
    def test_all_pass(self):
        items = [
            {"item": "A", "required": True, "checked": True, "result": "pass"},
            {"item": "B", "required": False, "checked": True, "result": "pass"},
        ]
        assert compute_node_check_result(items) == "pass"

    def test_required_fail(self):
        items = [
            {"item": "A", "required": True, "checked": True, "result": "fail"},
            {"item": "B", "required": False, "checked": True, "result": "pass"},
        ]
        assert compute_node_check_result(items) == "fail"

    def test_partial(self):
        items = [
            {"item": "A", "required": True, "checked": True, "result": "pass"},
            {"item": "B", "required": False, "checked": False, "result": None},
        ]
        assert compute_node_check_result(items) == "partial"

    def test_empty(self):
        assert compute_node_check_result([]) == "pass"


class TestTimeline:
    def test_generates_8_nodes(self):
        statuses = {f"E{i}": "pending" for i in range(1, 9)}
        tl = get_flow_timeline(statuses)
        assert len(tl) == 8
        assert tl[0]["code"] == "E1"
        assert tl[7]["code"] == "E8"

    def test_current_node_marking(self):
        statuses = {
            "E1": "completed",
            "E2": "completed",
            "E3": "pending",
            "E4": "pending",
            "E5": "pending",
            "E6": "pending",
            "E7": "pending",
            "E8": "pending",
        }
        tl = get_flow_timeline(statuses)
        current = [n for n in tl if n["is_current"]]
        assert len(current) == 1
        assert current[0]["code"] == "E3"
