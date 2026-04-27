"""RedisStreamsEventBus — EventBus 的 Redis Streams 实现 (T5.1.2).

设计:
- 基于 redis.asyncio (原 aioredis, 已并入 redis-py 5.x)
- topic 命名: {prefix}.{tenant_id}.{aggregate_type}  (aggregate_id 不参与 topic, 在 stream 内用
  entry sequence 保证同 aggregate_id 顺序)
- 发布: XADD + MAXLEN ~N (approximate 近似裁剪, 性能优先)
- 订阅: XREADGROUP + consumer group + 自动 MKSTREAM
- 回放: XRANGE after_event_id onwards
- 确认: XACK
- 反序列化: 按 event_type 查 schema_registry, Pydantic 校验 payload

注入 redis_client (而非 URL) 支持:
- 生产: 传 aioredis.from_url(...)
- 测试: 传 fakeredis.FakeAsyncRedis()
- 环境: 传自定义连接池
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Optional
from uuid import UUID

import structlog

from shared.events.schemas.base import OntologyEvent

from .event_bus import EventBus, EventEnvelope

logger = structlog.get_logger(__name__)


class RedisStreamsEventBus(EventBus):
    """基于 Redis Streams 的 EventBus 实现."""

    DEFAULT_BLOCK_MS = 200   # XREADGROUP 阻塞毫秒 (短周期响应取消)
    DEFAULT_READ_COUNT = 64  # 单次 XREADGROUP 读取条数

    def __init__(
        self,
        *,
        redis_client: Any,
        schema_registry: dict[str, type[OntologyEvent]],
        topic_prefix: str = "ontology",
        block_ms: int | None = None,
    ) -> None:
        """构造.

        Args:
            redis_client: aioredis.Redis 或 fakeredis.FakeAsyncRedis 实例
                          (调用方负责连接 / decode_responses=True)
            schema_registry: event_type 字符串 → OntologyEvent 子类的映射,
                             订阅侧据此反序列化 payload
            topic_prefix:    topic 命名前缀 (默认 "ontology")
        """
        self._redis = redis_client
        self._schemas = schema_registry
        self._prefix = topic_prefix
        self._block_ms = block_ms if block_ms is not None else self.DEFAULT_BLOCK_MS
        self._closed = False

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _topic_for(self, *, tenant_id: UUID, aggregate_type: str) -> str:
        return f"{self._prefix}.{tenant_id}.{aggregate_type}"

    def _envelope_to_fields(self, envelope: EventEnvelope) -> dict[str, str]:
        """EventEnvelope → Redis stream fields (全 str)."""
        return {
            "event_id": envelope.event_id,
            "aggregate_id": envelope.aggregate_id,
            "aggregate_type": envelope.aggregate_type,
            "event_type": envelope.event_type,
            "tenant_id": str(envelope.tenant_id),
            "occurred_at": envelope.occurred_at.isoformat(),
            "schema_version": envelope.schema_version,
            "causation_id": envelope.causation_id or "",
            "correlation_id": envelope.correlation_id or "",
            "payload": envelope.payload.model_dump_json(),
        }

    def _fields_to_envelope(
        self, fields: dict[str, str]
    ) -> EventEnvelope:
        """Redis stream fields → EventEnvelope (Pydantic 校验 payload)."""
        event_type = fields["event_type"]
        payload_cls = self._schemas.get(event_type)
        if payload_cls is None:
            raise ValueError(
                f"未注册的 event_type: {event_type}. "
                f"请在 schema_registry 中登记对应的 OntologyEvent 子类."
            )
        payload_dict = json.loads(fields["payload"])
        payload = payload_cls.model_validate(payload_dict)

        return EventEnvelope(
            event_id=fields["event_id"],
            aggregate_id=fields["aggregate_id"],
            aggregate_type=fields["aggregate_type"],
            event_type=event_type,
            tenant_id=UUID(fields["tenant_id"]),
            occurred_at=datetime.fromisoformat(fields["occurred_at"]),
            schema_version=fields["schema_version"],
            payload=payload,
            causation_id=fields.get("causation_id") or None,
            correlation_id=fields.get("correlation_id") or None,
        )

    async def _ensure_group(self, topic: str, consumer_group: str) -> None:
        """幂等建 group (不存在则创建, 存在则忽略)."""
        try:
            await self._redis.xgroup_create(
                name=topic,
                groupname=consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:  # noqa: BLE001
            # BUSYGROUP 错误表示 group 已存在, 正常跳过
            if "BUSYGROUP" not in str(exc):
                raise

    # ------------------------------------------------------------------
    # EventBus 契约实现
    # ------------------------------------------------------------------

    async def publish(
        self,
        envelope: EventEnvelope,
        *,
        maxlen: int = 100_000,
    ) -> str:
        topic = self._topic_for(
            tenant_id=envelope.tenant_id,
            aggregate_type=envelope.aggregate_type,
        )
        fields = self._envelope_to_fields(envelope)
        entry_id: str = await self._redis.xadd(
            name=topic,
            fields=fields,
            maxlen=maxlen,
            approximate=True,
        )
        logger.debug(
            "event_published",
            topic=topic,
            event_id=envelope.event_id,
            aggregate_id=envelope.aggregate_id,
            entry_id=entry_id,
        )
        return entry_id

    async def subscribe(
        self,
        *,
        consumer_group: str,
        topics: list[str],
        handler: Callable[[EventEnvelope], Awaitable[None]],
        start_from: str = ">",
    ) -> None:
        # 幂等建 group
        for topic in topics:
            await self._ensure_group(topic, consumer_group)

        consumer_name = f"{consumer_group}-{id(self)}"
        streams = dict.fromkeys(topics, start_from)

        logger.info(
            "subscribe_started",
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            topics=topics,
        )

        # 轮询周期: 用非阻塞 XREADGROUP + 小睡眠, 保证 cancel/close 响应快
        poll_interval_sec = max(self._block_ms / 1000.0, 0.01)

        while not self._closed:
            try:
                resp = await self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams=streams,
                    count=self.DEFAULT_READ_COUNT,
                    # block=None -> 非阻塞, 无消息立即返回空列表
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("xreadgroup_failed", error=str(exc))
                await asyncio.sleep(poll_interval_sec)
                continue

            if not resp:
                await asyncio.sleep(poll_interval_sec)
                continue

            for topic_name, entries in resp:
                for entry_id, fields in entries:
                    try:
                        env = self._fields_to_envelope(fields)
                    except ValueError as exc:
                        logger.error(
                            "deserialize_failed",
                            topic=topic_name,
                            entry_id=entry_id,
                            error=str(exc),
                        )
                        # 无法反序列化的消息也 ACK 避免重复投递死信
                        await self._redis.xack(topic_name, consumer_group, entry_id)
                        continue

                    try:
                        await handler(env)
                        await self._redis.xack(topic_name, consumer_group, entry_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "handler_failed",
                            topic=topic_name,
                            event_id=env.event_id,
                            error=str(exc),
                        )
                        # 失败不 ACK, 走 XPENDING 由 DLQ / 重试机制兜底

    async def replay(
        self,
        *,
        topic: str,
        after_event_id: Optional[str] = None,
        limit: int = 1000,
    ) -> AsyncIterator[EventEnvelope]:
        start_id = after_event_id or "-"
        # XRANGE name start end COUNT N
        entries = await self._redis.xrange(topic, min=start_id, max="+", count=limit)
        for entry_id, fields in entries:
            try:
                yield self._fields_to_envelope(fields)
            except ValueError as exc:
                logger.error(
                    "replay_deserialize_failed",
                    topic=topic,
                    entry_id=entry_id,
                    error=str(exc),
                )
                continue

    async def ack(
        self,
        *,
        topic: str,
        consumer_group: str,
        event_id: str,
    ) -> None:
        await self._redis.xack(topic, consumer_group, event_id)

    async def close(self) -> None:
        """幂等关闭. 不负责关闭外部注入的 redis_client (调用方管理)."""
        self._closed = True
