"""Tool Registry — 统一工具注册与发现

为 Agent 间工具调用提供动态注册、查询、LLM 格式化能力。
支持从 SkillAgent 自动注册，也支持从 MCP agent_registry 静态数据导入。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ToolDefinition:
    """单个工具的完整定义"""

    tool_id: str  # e.g. "discount_guard.detect_anomaly"
    agent_id: str  # owning agent
    action: str  # action name
    description: str  # what the tool does
    input_schema: dict[str, Any]  # JSON Schema for parameters
    output_schema: dict[str, Any] | None = None  # optional output schema
    requires_auth: bool = False
    risk_level: str = "low"  # from ActionConfig if available


class ToolRegistry:
    """Singleton tool registry for inter-agent tool discovery and invocation.

    线程安全的单例实现，支持：
    - 手动注册单个工具
    - 从 SkillAgent 批量自动注册
    - 按关键词搜索工具
    - 导出为 LLM function-calling 格式
    """

    _instance: ToolRegistry | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        """获取全局单例。双重检查锁定，线程安全。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.info("tool_registry_created")
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）。"""
        with cls._lock:
            cls._instance = None

    # ── 注册 ───────────────────────────────────────────────────────────────

    def register(self, tool: ToolDefinition) -> None:
        """注册一个工具定义。若 tool_id 已存在则覆盖。"""
        self._tools[tool.tool_id] = tool
        logger.debug(
            "tool_registered",
            tool_id=tool.tool_id,
            agent_id=tool.agent_id,
            action=tool.action,
        )

    def register_agent(self, agent: Any) -> int:
        """从 SkillAgent 实例自动注册其所有 action。

        使用 agent.get_supported_actions() 获取 action 列表，
        使用 agent.get_action_config(action) 获取 risk_level 等元数据。

        Args:
            agent: SkillAgent 实例（需要 agent_id, description, get_supported_actions, get_action_config）

        Returns:
            成功注册的工具数量
        """
        count = 0
        agent_id: str = agent.agent_id
        agent_description: str = getattr(agent, "description", "")

        try:
            actions: list[str] = agent.get_supported_actions()
        except NotImplementedError:
            logger.warning("agent_no_supported_actions", agent_id=agent_id)
            return 0

        for action in actions:
            tool_id = f"{agent_id}.{action}"

            # 尝试从 get_action_config 获取 risk_level
            risk_level = "low"
            try:
                config = agent.get_action_config(action)
                risk_level = config.risk_level
            except (AttributeError, TypeError):
                pass

            # 尝试从 MCP agent_registry 获取更详细的 schema
            input_schema = self._lookup_mcp_schema(agent_id, action)

            tool = ToolDefinition(
                tool_id=tool_id,
                agent_id=agent_id,
                action=action,
                description=f"[{agent_id}] {action}" if not agent_description else f"{agent_description} — {action}",
                input_schema=input_schema,
                output_schema=None,
                requires_auth=False,
                risk_level=risk_level,
            )
            self.register(tool)
            count += 1

        logger.info(
            "agent_tools_registered",
            agent_id=agent_id,
            count=count,
        )
        return count

    def _lookup_mcp_schema(self, agent_id: str, action: str) -> dict[str, Any]:
        """从 MCP agent_registry 查找该 action 的 inputSchema。

        查找键格式为 "{agent_id}__{action}"，匹配 agent_registry.py 中的命名约定。
        若未找到则返回空 object schema。
        """
        try:
            from services.mcp_server.src.agent_registry import TOOL_REGISTRY as MCP_REGISTRY
        except ImportError:
            # MCP server 模块不可用时静默降级
            return {"type": "object", "properties": {}}

        mcp_key = f"{agent_id}__{action}"
        entry = MCP_REGISTRY.get(mcp_key)
        if entry and "inputSchema" in entry:
            return entry["inputSchema"]

        return {"type": "object", "properties": {}}

    def import_from_mcp_registry(self) -> int:
        """从 MCP TOOL_REGISTRY 批量导入所有工具定义。

        Returns:
            成功导入的工具数量
        """
        try:
            from services.mcp_server.src.agent_registry import TOOL_REGISTRY as MCP_REGISTRY
        except ImportError:
            logger.warning("mcp_registry_import_failed", reason="module not found")
            return 0

        count = 0
        for tool_name, entry in MCP_REGISTRY.items():
            agent_id = entry.get("agent_id", "")
            action = entry.get("action", "")
            if not agent_id or not action:
                continue

            tool_id = f"{agent_id}.{action}"
            # 保留已注册工具的 risk_level（来自 ActionConfig），MCP 仅补充 schema
            existing = self._tools.get(tool_id)
            tool = ToolDefinition(
                tool_id=tool_id,
                agent_id=agent_id,
                action=action,
                description=entry.get("description", ""),
                input_schema=entry.get("inputSchema", {"type": "object", "properties": {}}),
                output_schema=None,
                requires_auth=False,
                risk_level=existing.risk_level if existing else "low",
            )
            self._tools[tool_id] = tool
            count += 1

        logger.info("mcp_registry_imported", count=count)
        return count

    # ── 查询 ───────────────────────────────────────────────────────────────

    def get_tool(self, tool_id: str) -> ToolDefinition | None:
        """按 tool_id 精确查找。"""
        return self._tools.get(tool_id)

    def search_tools(
        self,
        query: str,
        agent_id: str | None = None,
    ) -> list[ToolDefinition]:
        """按关键词搜索工具（匹配 tool_id 或 description）。

        Args:
            query: 搜索关键词（不区分大小写）
            agent_id: 可选，限定搜索范围到某个 agent

        Returns:
            匹配的 ToolDefinition 列表
        """
        query_lower = query.lower()
        results: list[ToolDefinition] = []

        for tool in self._tools.values():
            if agent_id and tool.agent_id != agent_id:
                continue
            if query_lower in tool.tool_id.lower() or query_lower in tool.description.lower():
                results.append(tool)

        return results

    def list_tools(self, agent_id: str | None = None) -> list[ToolDefinition]:
        """列出所有工具，可按 agent_id 过滤。"""
        if agent_id:
            return [t for t in self._tools.values() if t.agent_id == agent_id]
        return list(self._tools.values())

    def get_tools_for_llm(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """格式化工具列表为 LLM function-calling schema（OpenAI 兼容格式）。

        Args:
            agent_id: 可选，仅导出某 agent 的工具

        Returns:
            LLM function tool 定义列表
        """
        tools = self.list_tools(agent_id=agent_id)
        result: list[dict[str, Any]] = []

        for tool in tools:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.tool_id,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )

        return result

    # ── 统计 ───────────────────────────────────────────────────────────────

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def get_agent_ids(self) -> list[str]:
        """返回所有已注册工具的 agent_id 去重列表。"""
        return sorted(set(t.agent_id for t in self._tools.values()))
