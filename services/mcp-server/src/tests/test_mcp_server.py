"""Comprehensive tests for TunxiangOS MCP Server.

Tests cover:
- Tool registry completeness (all 73 skill agent actions + extras)
- JSON Schema validation for every tool
- MCP server list_tools / call_tool integration
- Tool execution routing to correct agents
- Error handling for unknown tools
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agent_registry import (
    TOOL_REGISTRY,
    get_skill_agent_tool_count,
    get_tool_entry,
    get_tool_names,
    get_tools_by_agent,
)
from mcp.types import Tool
from src.server import _execute_tool, _serialise_result, _stub_result, server, list_tools as _list_tools


# ===========================================================================
# Registry tests
# ===========================================================================


class TestToolRegistry:
    """Test the agent registry is complete and well-formed."""

    def test_skill_agent_tool_count_is_73(self) -> None:
        """The 9 Skill Agents should expose exactly 73 actions."""
        assert get_skill_agent_tool_count() == 73

    def test_total_tool_count(self) -> None:
        """Total tools = 73 skill + 3 master + 2 planner + 5 event_bus = 83."""
        assert len(TOOL_REGISTRY) == 83

    def test_all_tool_names_use_double_underscore(self) -> None:
        """Every tool name must follow {agent_id}__{action} pattern."""
        for name in get_tool_names():
            assert "__" in name, f"Tool name {name} missing __ separator"
            parts = name.split("__", 1)
            assert len(parts) == 2
            assert len(parts[0]) > 0
            assert len(parts[1]) > 0

    def test_each_tool_has_required_fields(self) -> None:
        """Every entry has agent_id, action, description, inputSchema."""
        for name, entry in TOOL_REGISTRY.items():
            assert "agent_id" in entry, f"{name}: missing agent_id"
            assert "action" in entry, f"{name}: missing action"
            assert "description" in entry, f"{name}: missing description"
            assert "inputSchema" in entry, f"{name}: missing inputSchema"

    def test_input_schema_is_valid_json_schema(self) -> None:
        """Each inputSchema should be a valid JSON Schema object type."""
        for name, entry in TOOL_REGISTRY.items():
            schema = entry["inputSchema"]
            assert isinstance(schema, dict), f"{name}: schema not a dict"
            assert schema.get("type") == "object", f"{name}: schema type not 'object'"
            # properties should be a dict if present
            if "properties" in schema:
                assert isinstance(schema["properties"], dict), f"{name}: properties not dict"

    def test_descriptions_are_chinese(self) -> None:
        """All descriptions should contain Chinese characters."""
        for name, entry in TOOL_REGISTRY.items():
            desc = entry["description"]
            has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in desc)
            assert has_chinese, f"{name}: description has no Chinese: {desc}"

    def test_tool_name_matches_entry(self) -> None:
        """Tool name prefix should match agent_id and suffix should match action."""
        for name, entry in TOOL_REGISTRY.items():
            expected_name = f"{entry['agent_id']}__{entry['action']}"
            assert name == expected_name, f"Key {name} != constructed {expected_name}"


class TestToolRegistryByAgent:
    """Test each agent has the expected number of actions."""

    EXPECTED_COUNTS = {
        "discount_guard": 6,
        "smart_menu": 8,
        "serve_dispatch": 7,
        "member_insight": 9,
        "inventory_alert": 9,
        "finance_audit": 7,
        "store_inspect": 7,
        "smart_service": 9,
        "private_ops": 11,
        "master": 3,
        "planner": 2,
        "event_bus": 5,
    }

    @pytest.mark.parametrize("agent_id,expected_count", EXPECTED_COUNTS.items())
    def test_agent_tool_count(self, agent_id: str, expected_count: int) -> None:
        tools = get_tools_by_agent(agent_id)
        assert len(tools) == expected_count, (
            f"{agent_id}: expected {expected_count} tools, got {len(tools)}: "
            f"{list(tools.keys())}"
        )

    def test_all_9_skill_agents_present(self) -> None:
        skill_agents = {
            e["agent_id"] for e in TOOL_REGISTRY.values()
            if e["agent_id"] not in ("master", "planner", "event_bus")
        }
        assert len(skill_agents) == 9
        expected = {
            "discount_guard", "smart_menu", "serve_dispatch",
            "member_insight", "inventory_alert", "finance_audit",
            "store_inspect", "smart_service", "private_ops",
        }
        assert skill_agents == expected


class TestToolLookup:
    """Test tool lookup helpers."""

    def test_get_tool_entry_found(self) -> None:
        entry = get_tool_entry("discount_guard__detect_discount_anomaly")
        assert entry is not None
        assert entry["agent_id"] == "discount_guard"
        assert entry["action"] == "detect_discount_anomaly"

    def test_get_tool_entry_not_found(self) -> None:
        entry = get_tool_entry("nonexistent__tool")
        assert entry is None

    def test_get_tool_names_returns_list(self) -> None:
        names = get_tool_names()
        assert isinstance(names, list)
        assert len(names) == 83


# ===========================================================================
# Schema validation tests for specific tools
# ===========================================================================


class TestSpecificToolSchemas:
    """Validate schemas for representative tools from each agent."""

    def test_discount_anomaly_schema_has_order(self) -> None:
        entry = get_tool_entry("discount_guard__detect_discount_anomaly")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "order" in props
        assert "threshold" in props

    def test_smart_menu_simulate_cost_schema(self) -> None:
        entry = get_tool_entry("smart_menu__simulate_cost")
        assert entry is not None
        schema = entry["inputSchema"]
        assert "bom_items" in schema["properties"]
        assert "target_price_fen" in schema["properties"]
        assert "bom_items" in schema.get("required", [])

    def test_serve_dispatch_predict_serve_time_schema(self) -> None:
        entry = get_tool_entry("serve_dispatch__predict_serve_time")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "dish_count" in props
        assert "has_complex_dish" in props

    def test_member_insight_rfm_schema(self) -> None:
        entry = get_tool_entry("member_insight__analyze_rfm")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "members" in props
        assert props["members"]["type"] == "array"

    def test_inventory_predict_consumption_schema(self) -> None:
        entry = get_tool_entry("inventory_alert__predict_consumption")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "daily_usage" in props
        assert "days_ahead" in props

    def test_finance_revenue_anomaly_schema(self) -> None:
        entry = get_tool_entry("finance_audit__detect_revenue_anomaly")
        assert entry is not None
        schema = entry["inputSchema"]
        assert "actual_revenue_fen" in schema["properties"]
        assert "actual_revenue_fen" in schema.get("required", [])

    def test_store_inspect_health_check_schema(self) -> None:
        entry = get_tool_entry("store_inspect__health_check")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "devices" in props

    def test_smart_service_handle_complaint_schema(self) -> None:
        entry = get_tool_entry("smart_service__handle_complaint")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "type" in props
        assert "enum" in props["type"]

    def test_private_ops_score_performance_schema(self) -> None:
        entry = get_tool_entry("private_ops__score_performance")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "role" in props
        assert "metrics" in props
        assert props["role"]["type"] == "string"

    def test_master_dispatch_schema(self) -> None:
        entry = get_tool_entry("master__dispatch")
        assert entry is not None
        schema = entry["inputSchema"]
        assert "agent_id" in schema["properties"]
        assert "action" in schema["properties"]
        assert "params" in schema["properties"]

    def test_planner_generate_plan_schema(self) -> None:
        entry = get_tool_entry("planner__generate_daily_plan")
        assert entry is not None
        props = entry["inputSchema"]["properties"]
        assert "date" in props

    def test_event_bus_publish_schema(self) -> None:
        entry = get_tool_entry("event_bus__publish_event")
        assert entry is not None
        schema = entry["inputSchema"]
        assert "event_type" in schema["properties"]
        assert "source_agent" in schema["properties"]
        assert "store_id" in schema["properties"]


# ===========================================================================
# Serialisation helpers
# ===========================================================================


class TestSerialisation:
    """Test result serialisation helpers."""

    def test_serialise_dict(self) -> None:
        result = _serialise_result({"key": "value"})
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_serialise_object(self) -> None:
        class Obj:
            def __init__(self) -> None:
                self.x = 1
                self.y = "hello"
        result = _serialise_result(Obj())
        parsed = json.loads(result)
        assert parsed["x"] == 1
        assert parsed["y"] == "hello"

    def test_serialise_none(self) -> None:
        result = _serialise_result(None)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_serialise_list(self) -> None:
        result = _serialise_result([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_stub_result(self) -> None:
        result = _stub_result("test_agent", "test_action", {"foo": "bar"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["agent_id"] == "test_agent"
        assert parsed["action"] == "test_action"
        assert parsed["data"]["stub"] is True


# ===========================================================================
# MCP Server integration tests
# ===========================================================================


class TestMCPServerListTools:
    """Test the MCP server list_tools endpoint."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_all_tools(self) -> None:
        tools = await _list_tools()
        assert len(tools) == 83

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_objects(self) -> None:
        tools = await _list_tools()
        for tool in tools:
            assert isinstance(tool, Tool)
            assert tool.name is not None
            assert tool.description is not None
            assert tool.inputSchema is not None

    @pytest.mark.asyncio
    async def test_all_tool_names_in_registry(self) -> None:
        tools = await _list_tools()
        tool_names = {t.name for t in tools}
        registry_names = set(get_tool_names())
        assert tool_names == registry_names


from src.server import call_tool


class TestMCPServerCallTool:
    """Test tool execution (stub mode when agents unavailable)."""

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self) -> None:
        result = await _execute_tool("nonexistent__tool", {})
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self) -> None:
        contents = await call_tool("discount_guard__detect_discount_anomaly", {
            "order": {"total_amount_fen": 10000, "discount_amount_fen": 3000},
        })
        assert len(contents) == 1
        assert contents[0].type == "text"
        # Should be valid JSON
        parsed = json.loads(contents[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_call_tool_with_full_params(self) -> None:
        contents = await call_tool("smart_menu__classify_quadrant", {
            "total_sales": 200,
            "margin_rate": 0.4,
            "avg_sales": 100,
            "avg_margin": 0.3,
        })
        assert len(contents) == 1
        parsed = json.loads(contents[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_call_master_dispatch_stub(self) -> None:
        """Master dispatch should work (possibly stub mode)."""
        contents = await call_tool("master__dispatch", {
            "agent_id": "discount_guard",
            "action": "detect_discount_anomaly",
            "params": {"order": {"total_amount_fen": 10000, "discount_amount_fen": 5000}},
        })
        assert len(contents) == 1
        parsed = json.loads(contents[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_call_planner_stub(self) -> None:
        contents = await call_tool("planner__generate_daily_plan", {"date": "2026-03-26"})
        assert len(contents) == 1
        parsed = json.loads(contents[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_call_event_bus_get_all_types_stub(self) -> None:
        contents = await call_tool("event_bus__get_all_event_types", {})
        assert len(contents) == 1
        parsed = json.loads(contents[0].text)
        assert isinstance(parsed, dict)


# ===========================================================================
# Routing correctness tests
# ===========================================================================


class TestRoutingCorrectness:
    """Verify tool names route to the correct agent_id and action."""

    ROUTING_SAMPLES = [
        ("discount_guard__detect_discount_anomaly", "discount_guard", "detect_discount_anomaly"),
        ("smart_menu__optimize_menu", "smart_menu", "optimize_menu"),
        ("serve_dispatch__predict_serve_time", "serve_dispatch", "predict_serve_time"),
        ("member_insight__analyze_rfm", "member_insight", "analyze_rfm"),
        ("inventory_alert__analyze_waste", "inventory_alert", "analyze_waste"),
        ("finance_audit__snapshot_kpi", "finance_audit", "snapshot_kpi"),
        ("store_inspect__diagnose_fault", "store_inspect", "diagnose_fault"),
        ("smart_service__evaluate_effectiveness", "smart_service", "evaluate_effectiveness"),
        ("private_ops__generate_beo", "private_ops", "generate_beo"),
        ("master__route_intent", "master", "route_intent"),
        ("planner__approve_plan", "planner", "approve_plan"),
        ("event_bus__publish_event", "event_bus", "publish_event"),
    ]

    @pytest.mark.parametrize("tool_name,expected_agent,expected_action", ROUTING_SAMPLES)
    def test_routing(self, tool_name: str, expected_agent: str, expected_action: str) -> None:
        entry = get_tool_entry(tool_name)
        assert entry is not None, f"Tool {tool_name} not found"
        assert entry["agent_id"] == expected_agent
        assert entry["action"] == expected_action


# ===========================================================================
# Full action list verification
# ===========================================================================


class TestFullActionList:
    """Verify every single action from each skill agent is registered."""

    def test_discount_guard_actions(self) -> None:
        expected = [
            "detect_discount_anomaly", "scan_store_licenses", "scan_all_licenses",
            "get_financial_report", "explain_voucher", "reconciliation_status",
        ]
        tools = get_tools_by_agent("discount_guard")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_smart_menu_actions(self) -> None:
        expected = [
            "simulate_cost", "recommend_pilot_stores", "run_dish_review",
            "check_launch_readiness", "scan_dish_risks", "inspect_dish_quality",
            "classify_quadrant", "optimize_menu",
        ]
        tools = get_tools_by_agent("smart_menu")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_serve_dispatch_actions(self) -> None:
        expected = [
            "predict_serve_time", "optimize_schedule", "analyze_traffic",
            "predict_staffing_needs", "detect_order_anomaly",
            "trigger_chain_alert", "balance_workload",
        ]
        tools = get_tools_by_agent("serve_dispatch")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_member_insight_actions(self) -> None:
        expected = [
            "analyze_rfm", "detect_signals", "detect_competitor",
            "trigger_journey", "get_churn_risks", "process_bad_review",
            "monitor_service_quality", "handle_complaint", "collect_feedback",
        ]
        tools = get_tools_by_agent("member_insight")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_inventory_alert_actions(self) -> None:
        expected = [
            "monitor_inventory", "predict_consumption", "generate_restock_alerts",
            "check_expiration", "optimize_stock_levels", "compare_supplier_prices",
            "evaluate_supplier", "scan_contract_risks", "analyze_waste",
        ]
        tools = get_tools_by_agent("inventory_alert")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_finance_audit_actions(self) -> None:
        expected = [
            "get_financial_report", "detect_revenue_anomaly", "snapshot_kpi",
            "forecast_orders", "generate_biz_insight", "match_scenario",
            "analyze_order_trend",
        ]
        tools = get_tools_by_agent("finance_audit")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_store_inspect_actions(self) -> None:
        expected = [
            "health_check", "diagnose_fault", "suggest_runbook",
            "predict_maintenance", "security_advice", "food_safety_status",
            "store_dashboard",
        ]
        tools = get_tools_by_agent("store_inspect")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_smart_service_actions(self) -> None:
        expected = [
            "analyze_feedback", "handle_complaint", "generate_improvements",
            "assess_training_needs", "generate_training_plan",
            "track_training_progress", "evaluate_effectiveness",
            "analyze_skill_gaps", "manage_certificates",
        ]
        tools = get_tools_by_agent("smart_service")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_private_ops_actions(self) -> None:
        expected = [
            "get_private_domain_dashboard", "trigger_campaign", "advance_journey",
            "optimize_shift", "score_performance", "analyze_labor_cost",
            "warn_attendance", "create_reservation", "manage_banquet",
            "generate_beo", "allocate_seating",
        ]
        tools = get_tools_by_agent("private_ops")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_master_actions(self) -> None:
        expected = ["dispatch", "route_intent", "multi_agent_execute"]
        tools = get_tools_by_agent("master")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_planner_actions(self) -> None:
        expected = ["generate_daily_plan", "approve_plan"]
        tools = get_tools_by_agent("planner")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual

    def test_event_bus_actions(self) -> None:
        expected = [
            "publish_event", "get_event_chain", "get_stream",
            "register_handler", "get_all_event_types",
        ]
        tools = get_tools_by_agent("event_bus")
        actual = sorted(e["action"] for e in tools.values())
        assert sorted(expected) == actual
