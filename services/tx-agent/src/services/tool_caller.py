"""Tool Caller — 跨 Agent 工具调用执行器

通过 MasterAgent.dispatch 路由调用，支持审计日志记录。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from .tool_registry import ToolDefinition, ToolRegistry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..agents.master import MasterAgent

logger = structlog.get_logger(__name__)


class ToolCallError(Exception):
    """工具调用错误"""

    def __init__(self, tool_id: str, message: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"ToolCallError[{tool_id}]: {message}")


class ToolCaller:
    """Execute tools across agents with audit trail.

    通过 MasterAgent.dispatch 机制路由调用，确保：
    1. 工具存在性校验
    2. 路由到正确的 agent + action
    3. 跨 Agent 调用审计记录
    """

    def __init__(
        self,
        master: MasterAgent,
        registry: ToolRegistry,
        db: AsyncSession | None = None,
    ) -> None:
        self.master = master
        self.registry = registry
        self.db = db

    async def call_tool(
        self,
        tool_id: str,
        params: dict[str, Any],
        caller_agent_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """调用一个工具，通过 MasterAgent.dispatch 路由。

        Args:
            tool_id: 工具标识，格式 "agent_id.action"
            params: 工具参数
            caller_agent_id: 调用方 agent_id（用于审计）
            tenant_id: 租户 ID
            session_id: 可选的会话 ID

        Returns:
            包含执行结果的字典

        Raises:
            ToolCallError: 工具未找到或执行失败
        """
        start_time = time.perf_counter()

        # 1. 查找工具定义
        tool = self.registry.get_tool(tool_id)
        if tool is None:
            raise ToolCallError(tool_id, "Tool not found in registry")

        # 2. 提取 agent_id 和 action
        target_agent_id = tool.agent_id
        target_action = tool.action

        logger.info(
            "tool_call_start",
            tool_id=tool_id,
            caller=caller_agent_id,
            target_agent=target_agent_id,
            target_action=target_action,
            tenant_id=tenant_id,
            session_id=session_id,
        )

        # 3. 通过 MasterAgent.dispatch 路由调用
        result = await self.master.dispatch(target_agent_id, target_action, params)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # 4. 构建返回值
        call_result: dict[str, Any] = {
            "tool_id": tool_id,
            "success": result.success,
            "data": result.data,
            "reasoning": result.reasoning,
            "confidence": result.confidence,
            "constraints_passed": result.constraints_passed,
            "error": result.error,
            "execution_ms": elapsed_ms,
            "caller_agent_id": caller_agent_id,
            "target_agent_id": target_agent_id,
            "target_action": target_action,
        }

        # 5. 审计日志
        logger.info(
            "tool_call_complete",
            tool_id=tool_id,
            caller=caller_agent_id,
            target_agent=target_agent_id,
            success=result.success,
            execution_ms=elapsed_ms,
        )

        # 6. 持久化审计记录（若 DB 可用）
        await self._log_call(
            tool_id=tool_id,
            caller_agent_id=caller_agent_id,
            target_agent_id=target_agent_id,
            target_action=target_action,
            tenant_id=tenant_id,
            session_id=session_id,
            params=params,
            result_data=call_result,
            success=result.success,
            elapsed_ms=elapsed_ms,
        )

        return call_result

    async def _log_call(
        self,
        *,
        tool_id: str,
        caller_agent_id: str,
        target_agent_id: str,
        target_action: str,
        tenant_id: str,
        session_id: str | None,
        params: dict[str, Any],
        result_data: dict[str, Any],
        success: bool,
        elapsed_ms: int,
    ) -> None:
        """将跨 Agent 调用写入 DB 审计表（若 DB 可用）。

        使用 SessionEvent 表记录 event_type='cross_agent_tool_call'。
        DB 不可用时静默跳过。
        """
        if self.db is None:
            return

        try:
            from ..models.session_event import SessionEvent

            event = SessionEvent(
                tenant_id=tenant_id,
                session_id=session_id or "tool_call",
                sequence_no=0,
                event_type="cross_agent_tool_call",
                agent_id=caller_agent_id,
                action=f"call:{tool_id}",
                input_json={
                    "tool_id": tool_id,
                    "target_agent_id": target_agent_id,
                    "target_action": target_action,
                    "params": params,
                },
                output_json={
                    "success": success,
                    "data": result_data.get("data", {}),
                    "error": result_data.get("error"),
                },
                reasoning=f"Cross-agent call: {caller_agent_id} → {target_agent_id}.{target_action}",
                tokens_used=0,
                duration_ms=elapsed_ms,
                inference_layer="internal",
            )
            self.db.add(event)
            await self.db.flush()
        except (ImportError, AttributeError, TypeError) as e:
            logger.debug("tool_call_audit_skip", reason=str(e))
