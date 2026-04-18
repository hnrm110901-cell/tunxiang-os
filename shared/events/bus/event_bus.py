"""EventBus 抽象基类 + EventEnvelope 信封 (T5.1.1).

设计目标:
- 将总线传输层 (Redis Streams / Kafka / NATS) 与消费侧解耦
- 所有 Agent / Subscriber 仅依赖本模块, 不引入 redis / kafka-python 等库
- EventEnvelope 承载跨服务事件必需的最小元数据 + 强类型 payload
- 按 aggregate_id 分区 (保证单聚合根事件有序)

后续:
- T5.1.2: RedisStreamsEventBus 实现
- T5.1.6: OntologySubscriber 基于本抽象订阅
- 未来 Phase: KafkaEventBus / NatsEventBus 以相同抽象替换
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Awaitable, Callable, Optional
from uuid import UUID

from shared.events.schemas.base import OntologyEvent


@dataclass(frozen=True)
class EventEnvelope:
    """统一事件信封 — 传输层无关的事件携带结构.

    约束:
    - frozen=True: 信封不可变, 防止总线传输中被篡改
    - payload 必须是 OntologyEvent 子类 (保证强类型 + 演进规则)
    - aggregate_id 是分区键, 保证同一聚合根的事件在总线上严格有序
    """

    event_id: str
    """事件全局唯一 ID (UUID 字符串形式)."""

    aggregate_id: str
    """聚合根 ID, 分区键. 同 aggregate_id 的事件在总线上严格有序."""

    aggregate_type: str
    """聚合根类型: 'order' | 'invoice' | 'cashflow' | ..."""

    event_type: str
    """事件类型点分字符串: 'order.paid' / 'invoice.verified' / ..."""

    tenant_id: UUID
    """租户 UUID, 用于 RLS 上下文注入."""

    occurred_at: datetime
    """业务发生时间 (非入库时间)."""

    schema_version: str
    """payload 的 schema 版本, 支持事件演进."""

    payload: OntologyEvent
    """强类型事件业务数据."""

    causation_id: Optional[str] = None
    """触发本事件的父事件 ID, 用于因果链追踪."""

    correlation_id: Optional[str] = None
    """同一业务流程的相关 ID, 用于跨服务关联."""


class EventBus(ABC):
    """事件总线抽象.

    RedisStreamsEventBus 是第一实现 (T5.1.2).
    未来可替换为 Kafka / NATS 等, 消费侧无感知.
    """

    @abstractmethod
    async def publish(
        self,
        envelope: EventEnvelope,
        *,
        maxlen: int = 100_000,
    ) -> str:
        """发布单条事件.

        Args:
            envelope: 事件信封
            maxlen: 底层 Stream 的近似长度上限 (Redis XADD MAXLEN ~N).
                    默认 10 万条滚动, 防止内存无限膨胀.

        Returns:
            底层 total-offset / stream-id 字符串, 供 ACK / replay 对齐.
        """
        ...

    @abstractmethod
    async def subscribe(
        self,
        *,
        consumer_group: str,
        topics: list[str],
        handler: Callable[[EventEnvelope], Awaitable[None]],
        start_from: str = ">",
    ) -> None:
        """持续订阅多个 topic.

        Args:
            consumer_group: 消费组名, 同组实例负载均衡
            topics: topic 列表 (点分命名: ontology.{tenant}.{aggregate_type})
            handler: 异步回调, 必须幂等. 出错走 DLQ.
            start_from: '>' 表示新消息; '0' 表示从头回放全部.
        """
        ...

    @abstractmethod
    async def replay(
        self,
        *,
        topic: str,
        after_event_id: Optional[str] = None,
        limit: int = 1000,
    ) -> AsyncIterator[EventEnvelope]:
        """按 event_id 之后回放历史事件 (投影器重建 / 新 Agent 追赶数据用).

        Args:
            topic: topic 名
            after_event_id: 从此 event_id 之后开始; None 表示从头
            limit: 单批上限

        Yields:
            EventEnvelope 序列
        """
        ...
        # 让 mypy 识别 AsyncIterator 返回值
        if False:  # pragma: no cover
            yield  # type: ignore[misc]

    @abstractmethod
    async def ack(
        self,
        *,
        topic: str,
        consumer_group: str,
        event_id: str,
    ) -> None:
        """ACK 单条事件 (consumer-group 模式必调, 否则 XPENDING 会堆积)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭底层连接. 实现必须幂等 (多次调用安全)."""
        ...
