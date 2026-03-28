"""Event Bus — 事件驱动 Agent 协同网格

替代 MemoryBus 的被动查询模式，改为主动事件驱动：
- Agent 发布事件 → EventBus 触发所有注册的处理器
- 支持事件链路追踪（correlation_id）
- 当前为内存实现，生产环境可替换为 Redis Streams
"""
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class AgentEvent:
    """Agent 事件"""
    event_type: str
    source_agent: str
    store_id: str
    data: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """事件驱动 Agent 网格

    - register_handler: 注册 event_type → (agent_id, handler) 映射
    - publish: 发布事件，自动触发所有处理器
    - get_event_chain: 按 correlation_id 追踪事件链路
    - get_stream: 查询某类事件的最近 N 条
    """

    def __init__(self, max_per_stream: int = 1000):
        self._streams: dict[str, list[AgentEvent]] = defaultdict(list)
        self._handlers: dict[str, list[tuple[str, Callable]]] = defaultdict(list)
        self._max_per_stream = max_per_stream

    def register_handler(
        self,
        event_type: str,
        agent_id: str,
        handler: Callable,
    ) -> None:
        """注册事件处理器

        Args:
            event_type: 事件类型
            agent_id: 处理器所属 Agent ID
            handler: 处理函数，接收 AgentEvent 返回 dict
        """
        self._handlers[event_type].append((agent_id, handler))
        logger.info(
            "handler_registered",
            event_type=event_type,
            agent_id=agent_id,
        )

    async def publish(self, event: AgentEvent) -> list[dict]:
        """发布事件 -> 触发所有注册的处理器 -> 返回处理结果

        Args:
            event: 待发布的事件

        Returns:
            各处理器的执行结果列表
        """
        # 存入事件流
        stream = self._streams[event.event_type]
        stream.append(event)
        if len(stream) > self._max_per_stream:
            self._streams[event.event_type] = stream[-self._max_per_stream:]

        logger.info(
            "event_published",
            event_id=event.event_id,
            event_type=event.event_type,
            source_agent=event.source_agent,
            store_id=event.store_id,
            correlation_id=event.correlation_id,
        )

        # 触发所有处理器
        results: list[dict] = []
        handlers = self._handlers.get(event.event_type, [])

        for agent_id, handler in handlers:
            try:
                # 支持 sync 和 async handler
                import asyncio
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = handler(event)

                result_entry = {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "success": True,
                    "result": result,
                }
                results.append(result_entry)
                logger.info(
                    "handler_executed",
                    event_id=event.event_id,
                    agent_id=agent_id,
                    success=True,
                )
            except Exception as e:  # 事件分发兜底：单个handler异常不能阻塞其他handler执行
                result_entry = {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "success": False,
                    "error": str(e),
                }
                results.append(result_entry)
                logger.error(
                    "handler_failed",
                    event_id=event.event_id,
                    agent_id=agent_id,
                    error=str(e),
                    exc_info=True,
                )

        return results

    async def get_event_chain(self, correlation_id: str) -> list[AgentEvent]:
        """获取事件链路（一个 correlation_id 关联的所有事件）

        Args:
            correlation_id: 事件关联 ID

        Returns:
            按时间排序的事件列表
        """
        chain: list[AgentEvent] = []
        for events in self._streams.values():
            for event in events:
                if event.correlation_id == correlation_id:
                    chain.append(event)
        chain.sort(key=lambda e: e.timestamp)
        return chain

    def get_stream(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[AgentEvent]:
        """获取事件流（最近 N 条）

        Args:
            event_type: 事件类型
            limit: 最多返回条数

        Returns:
            按时间倒序的事件列表
        """
        events = self._streams.get(event_type, [])
        return list(reversed(events[-limit:]))

    def get_handler_count(self, event_type: str) -> int:
        """获取某事件类型的处理器数量"""
        return len(self._handlers.get(event_type, []))

    def get_all_event_types(self) -> list[str]:
        """获取所有已注册的事件类型"""
        return list(set(list(self._handlers.keys()) + list(self._streams.keys())))

    def clear(self) -> None:
        """清空所有事件和处理器（测试用）"""
        self._streams.clear()
        self._handlers.clear()


# ─── 预注册事件处理器映射 ───

DEFAULT_EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    "inventory_surplus": [
        ("smart_menu", "adjust_push_recommendations"),
        ("private_ops", "trigger_surplus_promotion"),
    ],
    "inventory_shortage": [
        ("smart_menu", "reduce_shortage_items"),
        ("serve_dispatch", "alert_kitchen_shortage"),
    ],
    "discount_violation": [
        ("discount_guard", "log_violation"),
        ("private_ops", "notify_store_manager"),
    ],
    "vip_arrival": [
        ("member_insight", "load_vip_preferences"),
        ("serve_dispatch", "assign_senior_waiter"),
    ],
    "daily_plan_generated": [
        ("private_ops", "notify_manager_for_approval"),
    ],
    "order_completed": [
        ("finance_audit", "update_daily_revenue"),
        ("inventory_alert", "deduct_ingredients"),
    ],
    "shift_handover": [
        ("finance_audit", "generate_shift_summary"),
        ("store_inspect", "trigger_shift_checklist"),
    ],
}


def create_default_event_bus() -> EventBus:
    """创建带预注册处理器的 EventBus（使用占位 handler）

    生产环境中，handler 应替换为实际的 Agent 方法调用。
    """
    bus = EventBus()
    for event_type, handlers in DEFAULT_EVENT_HANDLERS.items():
        for agent_id, action_name in handlers:
            # 占位处理器：记录事件并返回动作名
            def make_handler(aid: str, act: str) -> Callable:
                def handler(event: AgentEvent) -> dict:
                    return {
                        "agent_id": aid,
                        "action": act,
                        "event_type": event.event_type,
                        "store_id": event.store_id,
                        "processed": True,
                    }
                return handler

            bus.register_handler(event_type, agent_id, make_handler(agent_id, action_name))
    return bus
