"""AgentEventHandlerFactory — 将 EventBus handler 接入真实 MasterAgent.dispatch()

使用工厂模式创建 handler 函数，每个 handler 调用 MasterAgent.dispatch()
执行对应 Skill Agent 的动作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import structlog

from .event_bus import DEFAULT_EVENT_HANDLERS, AgentEvent, EventBus

if TYPE_CHECKING:
    from .master import MasterAgent

logger = structlog.get_logger()


class AgentEventHandlerFactory:
    """AgentEvent 处理器工厂，生成真实调用 MasterAgent 的 handler 函数"""

    def __init__(self, master_agent: "MasterAgent"):
        self.master = master_agent

    def make_handler(self, agent_id: str, action: str) -> Callable:
        """创建一个真实调用 MasterAgent.dispatch() 的 async handler"""

        async def handler(event: AgentEvent) -> dict:
            """从 AgentEvent 提取参数并调用对应 Skill Agent"""
            params = {
                "store_id": event.store_id,
                "tenant_id": event.tenant_id,
                "event_type": event.event_type,
                "event_data": event.data,
                "correlation_id": event.correlation_id,
                # 将 event.data 中的所有字段也展开为顶层参数
                **event.data,
            }

            try:
                result = await self.master.dispatch(agent_id, action, params)
                logger.info(
                    "event_handler_dispatched",
                    agent_id=agent_id,
                    action=action,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    success=result.success,
                )
                return {
                    "agent_id": agent_id,
                    "action": action,
                    "success": result.success,
                    "data": result.data or {},
                    "error": result.error,
                }
            except (RuntimeError, ValueError) as exc:
                logger.error(
                    "event_handler_dispatch_failed",
                    agent_id=agent_id,
                    action=action,
                    event_type=event.event_type,
                    error=str(exc),
                )
                return {"agent_id": agent_id, "action": action, "success": False, "error": str(exc)}

        return handler

    def build_event_bus(self) -> EventBus:
        """创建绑定真实 MasterAgent 的 EventBus"""
        bus = EventBus()

        for event_type, handlers in DEFAULT_EVENT_HANDLERS.items():
            for agent_id, action_name in handlers:
                real_handler = self.make_handler(agent_id, action_name)
                bus.register_handler(event_type, agent_id, real_handler)

        logger.info(
            "real_event_bus_created",
            event_types=len(DEFAULT_EVENT_HANDLERS),
            total_handlers=sum(len(h) for h in DEFAULT_EVENT_HANDLERS.values()),
        )
        return bus
