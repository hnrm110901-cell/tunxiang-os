"""TunxiangOS MCP Server - exposes all Agent actions as MCP tools.

Runs as a stdio-based MCP server. Any MCP-compatible client (Claude Desktop,
VS Code Copilot, etc.) can invoke these agent capabilities.

Usage:
    python -m src.server          # direct run
    tunxiang-mcp                  # via pyproject.toml entry point
"""

import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .agent_registry import TOOL_REGISTRY, get_tool_entry

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "tunxiang-agent"
SERVER_VERSION = "0.1.0"

# Agent backend base URL (Mac mini local API or cloud gateway)
AGENT_API_BASE = os.environ.get("TX_AGENT_API_BASE", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Bootstrap Agent runtime (in-process for local dev, HTTP for production)
# ---------------------------------------------------------------------------

_master = None
_planner = None
_event_bus = None


def _ensure_agent_path() -> None:
    """Add tx-agent src to sys.path so we can import agents directly."""
    agent_src = Path(__file__).resolve().parent.parent.parent / "tx-agent" / "src"
    if agent_src.exists() and str(agent_src) not in sys.path:
        sys.path.insert(0, str(agent_src))


def _init_agents() -> None:
    """Lazily initialise in-process Agent runtime."""
    global _master, _planner, _event_bus

    if _master is not None:
        return

    _ensure_agent_path()

    try:
        from agents.master import MasterAgent
        from agents.planner import DailyPlannerAgent
        from agents.event_bus import EventBus, create_default_event_bus
        from agents.skills.discount_guard import DiscountGuardAgent
        from agents.skills.smart_menu import SmartMenuAgent
        from agents.skills.serve_dispatch import ServeDispatchAgent
        from agents.skills.member_insight import MemberInsightAgent
        from agents.skills.inventory_alert import InventoryAlertAgent
        from agents.skills.finance_audit import FinanceAuditAgent
        from agents.skills.store_inspect import StoreInspectAgent
        from agents.skills.smart_service import SmartServiceAgent
        from agents.skills.private_ops import PrivateOpsAgent

        tenant_id = os.environ.get("TX_TENANT_ID", "default")
        store_id = os.environ.get("TX_STORE_ID", "store_001")

        _master = MasterAgent(tenant_id=tenant_id, store_id=store_id)

        skill_agents = [
            DiscountGuardAgent(tenant_id=tenant_id, store_id=store_id),
            SmartMenuAgent(tenant_id=tenant_id, store_id=store_id),
            ServeDispatchAgent(tenant_id=tenant_id, store_id=store_id),
            MemberInsightAgent(tenant_id=tenant_id, store_id=store_id),
            InventoryAlertAgent(tenant_id=tenant_id, store_id=store_id),
            FinanceAuditAgent(tenant_id=tenant_id, store_id=store_id),
            StoreInspectAgent(tenant_id=tenant_id, store_id=store_id),
            SmartServiceAgent(tenant_id=tenant_id, store_id=store_id),
            PrivateOpsAgent(tenant_id=tenant_id, store_id=store_id),
        ]

        for agent in skill_agents:
            _master.register(agent)

        _planner = DailyPlannerAgent(tenant_id=tenant_id, store_id=store_id)
        _event_bus = create_default_event_bus()

        logger.info(
            "agents_initialised",
            agent_count=len(skill_agents),
            tenant_id=tenant_id,
            store_id=store_id,
        )
    except ImportError as exc:
        logger.warning(
            "agent_import_failed",
            error=str(exc),
            hint="Running in stub mode - calls will return mock results",
        )
        _master = None


# ---------------------------------------------------------------------------
# Result serialisation helpers
# ---------------------------------------------------------------------------

def _serialise_result(obj: Any) -> str:
    """Convert an AgentResult (or any object) to a JSON string."""
    if obj is None:
        return json.dumps({"error": "No result"})
    if hasattr(obj, "__dict__"):
        data = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return json.dumps(data, ensure_ascii=False, default=str)
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, default=str)
    return json.dumps({"result": str(obj)}, ensure_ascii=False)


def _stub_result(agent_id: str, action: str, arguments: dict) -> str:
    """Return a stub response when agents are not available."""
    return json.dumps({
        "success": True,
        "action": action,
        "agent_id": agent_id,
        "data": {"stub": True, "message": f"Stub response for {agent_id}.{action}"},
        "reasoning": "Agent runtime not available - returning stub",
        "confidence": 0.0,
        "input_params": arguments,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool execution router
# ---------------------------------------------------------------------------

async def _execute_tool(tool_name: str, arguments: dict) -> str:
    """Route a tool call to the appropriate agent and return serialised result."""
    entry = get_tool_entry(tool_name)
    if entry is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    agent_id = entry["agent_id"]
    action = entry["action"]

    _init_agents()

    # --- Master Agent actions ---
    if agent_id == "master":
        if _master is None:
            return _stub_result(agent_id, action, arguments)

        if action == "dispatch":
            result = await _master.dispatch(
                arguments["agent_id"], arguments["action"], arguments.get("params", {})
            )
            return _serialise_result(result)

        if action == "route_intent":
            result = await _master.route_intent(
                arguments["intent"], arguments.get("params", {})
            )
            return _serialise_result(result)

        if action == "multi_agent_execute":
            results = await _master.multi_agent_execute(arguments["tasks"])
            return json.dumps(
                [json.loads(_serialise_result(r)) for r in results],
                ensure_ascii=False,
            )

    # --- Planner Agent actions ---
    elif agent_id == "planner":
        if _planner is None:
            return _stub_result(agent_id, action, arguments)

        if action == "generate_daily_plan":
            result = await _planner.generate_daily_plan(arguments.get("date", "today"))
            return json.dumps(result, ensure_ascii=False, default=str)

        if action == "approve_plan":
            result = _planner.__class__.approve_plan(
                arguments["plan"],
                arguments["approved_items"],
                arguments["rejected_items"],
                arguments.get("notes", ""),
            )
            return json.dumps(result, ensure_ascii=False, default=str)

    # --- EventBus actions ---
    elif agent_id == "event_bus":
        if _event_bus is None:
            return _stub_result(agent_id, action, arguments)

        if action == "publish_event":
            from agents.event_bus import AgentEvent
            event = AgentEvent(
                event_type=arguments["event_type"],
                source_agent=arguments["source_agent"],
                store_id=arguments["store_id"],
                data=arguments.get("data", {}),
            )
            results = await _event_bus.publish(event)
            return json.dumps(results, ensure_ascii=False, default=str)

        if action == "get_event_chain":
            events = await _event_bus.get_event_chain(arguments["correlation_id"])
            return json.dumps(
                [asdict(e) for e in events], ensure_ascii=False, default=str,
            )

        if action == "get_stream":
            events = _event_bus.get_stream(
                arguments["event_type"], arguments.get("limit", 100),
            )
            return json.dumps(
                [asdict(e) for e in events], ensure_ascii=False, default=str,
            )

        if action == "register_handler":
            # Register a no-op handler (real handlers are set up in agent init)
            _event_bus.register_handler(
                arguments["event_type"],
                arguments["agent_id"],
                lambda event: {"processed": True},
            )
            return json.dumps({"registered": True, "event_type": arguments["event_type"]})

        if action == "get_all_event_types":
            types = _event_bus.get_all_event_types()
            return json.dumps({"event_types": types})

    # --- Skill Agent actions (the 73 core tools) ---
    else:
        if _master is None:
            return _stub_result(agent_id, action, arguments)
        result = await _master.dispatch(agent_id, action, arguments)
        return _serialise_result(result)

    return json.dumps({"error": f"Unhandled: {agent_id}.{action}"})


# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all registered tools with their JSON Schema definitions."""
    tools: list[Tool] = []
    for tool_name, entry in TOOL_REGISTRY.items():
        tools.append(
            Tool(
                name=tool_name,
                description=entry["description"],
                inputSchema=entry["inputSchema"],
            )
        )
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool call and return the result."""
    logger.info("tool_called", tool=name, arguments=arguments)
    try:
        result_text = await _execute_tool(name, arguments)
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        logger.error("tool_error", tool=name, error=str(exc))
        result_text = json.dumps({
            "error": str(exc),
            "tool": name,
            "success": False,
        }, ensure_ascii=False)
    return [TextContent(type="text", text=result_text)]


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run the MCP server over stdio."""
    logger.info(
        "mcp_server_starting",
        server=SERVER_NAME,
        version=SERVER_VERSION,
        tool_count=len(TOOL_REGISTRY),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    """Synchronous entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
