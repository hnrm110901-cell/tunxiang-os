"""DomainEventConsumer — 从业务域 Redis Stream 消费事件，驱动 Agent 协同

从 trade_events / supply_events / finance_events / org_events 等 Stream 消费事件，
将其转换为 AgentEvent 并发布到内存 EventBus，触发已注册的 Skill Agent handler。

运行方式：作为后台 Task 在 tx-agent 启动时运行。
"""
import asyncio
import json
import os
from typing import Optional

import structlog

from ..services.daily_review_service import DailyReviewService
from .event_bus import AgentEvent, EventBus

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 高复杂度事件：需要 Orchestrator 多 Agent 联动处理
ORCHESTRATOR_EVENTS: frozenset[str] = frozenset({
    "supply.stock.zero",           # 库存清零 → 智能排菜+库存预警+私域运营 联动
    "supply.receiving.variance",   # 收货差异 → 财务稽核+供应链 联动
    "trade.discount.blocked",      # 折扣违规 → 折扣守护+财务稽核 联动
    "finance.cost_rate.exceeded",  # 成本超标 → 财务稽核+智能排菜 联动
    "org.attendance.exception",    # 考勤异常 → 门店质检+HR 联动
})

# 各域 Stream → 消费者组名
DOMAIN_STREAMS: dict[str, str] = {
    "trade_events":   "tx-agent-trade",
    "supply_events":  "tx-agent-supply",
    "finance_events": "tx-agent-finance",
    "org_events":     "tx-agent-org",
    "member_events":  "tx-agent-member",
}

# event_type 前缀 → source_agent 标识
DOMAIN_SOURCE_MAP: dict[str, str] = {
    "trade.":   "tx-trade",
    "supply.":  "tx-supply",
    "finance.": "tx-finance",
    "org.":     "tx-org",
    "member.":  "tx-member",
}


class DomainEventConsumer:
    """从业务域 Redis Stream 消费事件并桥接到 EventBus"""

    def __init__(
        self,
        event_bus: EventBus,
        tenant_id: Optional[str] = None,
        master_agent=None,  # MasterAgent 实例（可选）
    ):
        self.event_bus = event_bus
        self.tenant_id = tenant_id
        self.master_agent = master_agent
        self._redis = None
        self._running = False

    async def _get_redis(self) -> object:
        import redis.asyncio as aioredis
        if self._redis is None:
            self._redis = await aioredis.from_url(
                REDIS_URL, decode_responses=True,
                socket_connect_timeout=3, socket_timeout=3,
            )
        return self._redis

    async def _ensure_groups(self) -> None:
        """确保所有 Consumer Group 存在（幂等）"""
        redis = await self._get_redis()
        for stream_key, group_name in DOMAIN_STREAMS.items():
            try:
                await redis.xgroup_create(stream_key, group_name, id="$", mkstream=True)
            except Exception:  # noqa: BLE001 — BUSYGROUP 表示已存在，忽略
                pass

    async def _convert_to_agent_event(
        self, stream_key: str, fields: dict
    ) -> Optional[AgentEvent]:
        """将 Redis Stream 字段转换为 AgentEvent"""
        event_type = fields.get("event_type", "")
        store_id = fields.get("store_id", "") or ""
        tenant_id = fields.get("tenant_id", self.tenant_id or "")

        source_agent = "unknown"
        for prefix, src in DOMAIN_SOURCE_MAP.items():
            if event_type.startswith(prefix):
                source_agent = src
                break

        try:
            event_data = json.loads(fields.get("event_data", "{}"))
        except (json.JSONDecodeError, ValueError):
            event_data = {}

        return AgentEvent(
            event_type=event_type,
            source_agent=source_agent,
            store_id=store_id,
            data=event_data,
            event_id=fields.get("event_id", ""),
            correlation_id=fields.get("event_id", ""),
            tenant_id=tenant_id,
        )

    async def consume_once(self, stream_key: str, group_name: str) -> int:
        """消费一批消息，返回处理数量"""
        redis = await self._get_redis()
        consumer_name = f"agent-worker-{stream_key}"

        try:
            messages = await redis.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_key: ">"},
                count=20,
                block=100,
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("domain_event_consumer_read_failed", stream=stream_key, error=str(exc))
            return 0

        if not messages:
            return 0

        count = 0
        for _, entries in messages:
            for entry_id, fields in entries:
                agent_event = await self._convert_to_agent_event(stream_key, fields)
                if agent_event:
                    await self._dispatch(agent_event)
                    count += 1
                try:
                    await redis.xack(stream_key, group_name, entry_id)
                except (OSError, RuntimeError) as exc:
                    logger.warning("xack_failed", entry_id=entry_id, error=str(exc))

        return count

    async def _dispatch(self, event: AgentEvent) -> None:
        """根据事件类型选择分发策略：Orchestrator 多 Agent 协同 or EventBus 单 Agent 处理"""
        if self.master_agent and event.event_type in ORCHESTRATOR_EVENTS:
            # 高复杂度事件：AI 多 Agent 编排
            # 使用事件自身的 tenant_id，避免用 master 的 "system" 导致成本统计错误
            effective_tenant_id = event.tenant_id or self.tenant_id or "system"
            try:
                context = {
                    "store_id": event.store_id,
                    "tenant_id": effective_tenant_id,
                    "event_data": event.data,
                }
                # 传入事件级 tenant_id，让 Orchestrator 按真实租户计费和隔离日志
                result = await self.master_agent.orchestrate(
                    event, context, tenant_id=effective_tenant_id
                )
                logger.info(
                    "orchestrator_dispatched",
                    event_type=event.event_type,
                    tenant_id=effective_tenant_id,
                    plan_id=result.plan_id,
                    completed_steps=len(result.completed_steps),
                )
            except (RuntimeError, ValueError) as exc:
                # Orchestrator 失败时降级到 EventBus
                logger.warning(
                    "orchestrator_dispatch_failed_fallback_to_eventbus",
                    event_type=event.event_type,
                    error=str(exc),
                )
                await self.event_bus.publish(event)
        else:
            # 普通事件：EventBus 单 Agent 处理
            await self.event_bus.publish(event)

        # 日清节点推进（fire-and-forget，不影响主流程）
        store_id = event.store_id or event.data.get("store_id")
        if store_id and event.tenant_id:
            advanced_node = DailyReviewService.handle_event(
                tenant_id=event.tenant_id,
                store_id=str(store_id),
                event_type=event.event_type,
            )
            if advanced_node:
                logger.info(
                    "daily_review_node_advanced",
                    tenant_id=event.tenant_id,
                    store_id=str(store_id),
                    node_id=advanced_node,
                    event_type=event.event_type,
                )

    async def run(self) -> None:
        """主循环：持续消费所有域的事件"""
        self._running = True
        await self._ensure_groups()
        logger.info("domain_event_consumer_started", streams=list(DOMAIN_STREAMS.keys()))

        while self._running:
            tasks = [
                self.consume_once(stream_key, group_name)
                for stream_key, group_name in DOMAIN_STREAMS.items()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.5)  # 500ms 轮询间隔

    async def stop(self) -> None:
        """停止消费循环并关闭 Redis 连接"""
        self._running = False
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("domain_event_consumer_stopped")
