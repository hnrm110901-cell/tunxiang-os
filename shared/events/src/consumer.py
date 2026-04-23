"""EventConsumer -- Redis Streams 统一事件消费器（Consumer Group 模式）

特性：
- subscribe(event_type, handler) 注册事件处理器
- Consumer Group 确保每条消息只被组内一个消费者处理
- XACK 消费确认
- 3 次处理失败后移入 dead_letter stream
- 优雅关闭（stop 信号）
- Mock 模式（从 EventPublisher 的内存队列消费）
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Optional

import structlog

from .event_base import TxEvent
from .event_types import resolve_stream_key

logger = structlog.get_logger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DLQ_SUFFIX: str = "_dlq"
MAX_HANDLER_RETRIES: int = 3

# 事件处理器类型
EventHandler = Callable[[TxEvent], Awaitable[None]]


class EventConsumer:
    """Redis Streams 消费器

    Args:
        group_name:    消费者组名称（每个微服务用不同的组名）
        consumer_name: 消费者实例名称
        redis_url:     Redis 连接 URL。None 使用环境变量。
        mock:          Mock 模式，从内存队列消费。
    """

    def __init__(
        self,
        group_name: str,
        consumer_name: str,
        redis_url: str | None = None,
        *,
        mock: bool = False,
    ) -> None:
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._redis_url = redis_url or REDIS_URL
        self._mock = mock
        self._redis: Optional[object] = None
        self._running = False

        # event_type -> list[handler]
        self._handlers: dict[str, list[EventHandler]] = {}
        # 需要监听的 stream keys
        self._stream_keys: set[str] = set()

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """注册事件处理器。

        Args:
            event_type: 事件类型字符串，如 "order.created"
            handler:    异步处理函数，接收 TxEvent
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        self._stream_keys.add(resolve_stream_key(event_type))
        logger.info(
            "consumer_handler_registered",
            event_type=event_type,
            group=self.group_name,
            consumer=self.consumer_name,
        )

    # ------------------------------------------------------------------
    # Redis 连接
    # ------------------------------------------------------------------

    async def _get_redis(self) -> object:
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = await aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return self._redis

    async def _ensure_groups(self, redis: object) -> None:
        """确保所有需要的 Consumer Group 存在。"""
        import redis.asyncio as aioredis

        for stream_key in self._stream_keys:
            try:
                await redis.xgroup_create(  # type: ignore[union-attr]
                    stream_key,
                    self.group_name,
                    id="0",
                    mkstream=True,
                )
                logger.info(
                    "consumer_group_created",
                    group=self.group_name,
                    stream=stream_key,
                )
            except aioredis.ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    # ------------------------------------------------------------------
    # 消费主循环
    # ------------------------------------------------------------------

    async def start(
        self,
        batch_size: int = 10,
        block_ms: int = 1000,
    ) -> None:
        """开始消费（阻塞式循环，应在独立 asyncio Task 中运行）。

        Args:
            batch_size: 每次 XREADGROUP 拉取的最大消息数
            block_ms:   无新消息时阻塞等待的毫秒数
        """
        if self._mock:
            logger.info(
                "consumer_mock_mode",
                group=self.group_name,
                note="Mock consumer does not auto-poll; use drain_mock() instead.",
            )
            return

        if not self._stream_keys:
            logger.warning(
                "consumer_no_subscriptions",
                group=self.group_name,
            )
            return

        import redis.asyncio as aioredis

        redis = await self._get_redis()
        await self._ensure_groups(redis)

        self._running = True
        logger.info(
            "consumer_started",
            group=self.group_name,
            consumer=self.consumer_name,
            streams=sorted(self._stream_keys),
            batch_size=batch_size,
        )

        streams_arg = dict.fromkeys(self._stream_keys, ">")

        while self._running:
            try:
                messages: list | None = await redis.xreadgroup(  # type: ignore[union-attr]
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams=streams_arg,
                    count=batch_size,
                    block=block_ms,
                )
            except aioredis.ResponseError as exc:
                logger.error(
                    "consumer_xreadgroup_error",
                    group=self.group_name,
                    error=str(exc),
                    exc_info=True,
                )
                await asyncio.sleep(2)
                continue
            except OSError as exc:
                logger.warning(
                    "consumer_redis_connection_lost",
                    group=self.group_name,
                    error=str(exc),
                )
                self._redis = None
                await asyncio.sleep(5)
                redis = await self._get_redis()
                await self._ensure_groups(redis)
                streams_arg = dict.fromkeys(self._stream_keys, ">")
                continue

            if not messages:
                continue

            for stream_key, entries in messages:
                for entry_id, fields in entries:
                    await self._process_entry(redis, stream_key, entry_id, fields)

    async def stop(self) -> None:
        """优雅关闭消费者。"""
        self._running = False
        logger.info(
            "consumer_stop_requested",
            group=self.group_name,
            consumer=self.consumer_name,
        )
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[union-attr]
            self._redis = None

    # ------------------------------------------------------------------
    # 单条消息处理
    # ------------------------------------------------------------------

    async def _process_entry(
        self,
        redis: object,
        stream_key: str,
        entry_id: str,
        fields: dict[str, str],
    ) -> None:
        """处理单条 Stream 消息，分发给匹配的 handler。"""
        try:
            event = TxEvent.from_stream_fields(fields)
        except (KeyError, ValueError) as exc:
            logger.error(
                "consumer_deserialize_failed",
                entry_id=entry_id,
                stream_key=stream_key,
                error=str(exc),
                exc_info=True,
            )
            await self._send_to_dlq(redis, stream_key, entry_id, fields, str(exc))
            await redis.xack(stream_key, self.group_name, entry_id)  # type: ignore[union-attr]
            return

        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            # 没有匹配的 handler，ACK 跳过
            await redis.xack(stream_key, self.group_name, entry_id)  # type: ignore[union-attr]
            return

        for handler in handlers:
            success = await self._invoke_handler_with_retry(handler, event, stream_key, entry_id, fields, redis)
            if not success:
                # handler 重试耗尽，已送 DLQ
                break

        await redis.xack(stream_key, self.group_name, entry_id)  # type: ignore[union-attr]

    async def _invoke_handler_with_retry(
        self,
        handler: EventHandler,
        event: TxEvent,
        stream_key: str,
        entry_id: str,
        fields: dict[str, str],
        redis: object,
    ) -> bool:
        """调用 handler，最多重试 MAX_HANDLER_RETRIES 次。

        Returns:
            True 表示处理成功，False 表示重试耗尽已送 DLQ。
        """
        for attempt in range(1, MAX_HANDLER_RETRIES + 1):
            try:
                await handler(event)
                logger.debug(
                    "consumer_event_handled",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    entry_id=entry_id,
                    group=self.group_name,
                )
                return True
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "consumer_handler_retry",
                    attempt=attempt,
                    max_retries=MAX_HANDLER_RETRIES,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    error=str(exc),
                    exc_info=True,
                )
                if attempt < MAX_HANDLER_RETRIES:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        # 重试耗尽 -> DLQ
        logger.error(
            "consumer_handler_exhausted",
            event_type=event.event_type,
            event_id=event.event_id,
            entry_id=entry_id,
            group=self.group_name,
        )
        await self._send_to_dlq(redis, stream_key, entry_id, fields, "handler retries exhausted")
        return False

    # ------------------------------------------------------------------
    # Dead Letter Queue
    # ------------------------------------------------------------------

    async def _send_to_dlq(
        self,
        redis: object,
        stream_key: str,
        entry_id: str,
        fields: dict[str, str],
        error_msg: str,
    ) -> None:
        """将失败事件写入 Dead Letter Queue。"""
        from datetime import datetime, timezone

        dlq_key = stream_key + DLQ_SUFFIX
        dlq_fields = {
            **fields,
            "original_entry_id": entry_id,
            "original_stream": stream_key,
            "error_message": error_msg,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "consumer_group": self.group_name,
            "consumer_name": self.consumer_name,
        }

        try:
            await redis.xadd(  # type: ignore[union-attr]
                dlq_key,
                dlq_fields,
                maxlen=50_000,
                approximate=True,
            )
            logger.warning(
                "consumer_event_sent_to_dlq",
                dlq_stream=dlq_key,
                original_entry_id=entry_id,
                error_message=error_msg,
            )
        except (OSError, RuntimeError) as exc:
            logger.error(
                "consumer_dlq_write_failed",
                dlq_stream=dlq_key,
                original_entry_id=entry_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------

    async def drain_mock(self, publisher: object) -> int:
        """从 EventPublisher 的 Mock 队列消费所有待处理事件。

        仅在 Mock 模式下使用。逐条取出事件分发给匹配 handler。

        Args:
            publisher: EventPublisher 实例（mock=True）

        Returns:
            实际处理的事件数
        """
        from .publisher import EventPublisher

        if not isinstance(publisher, EventPublisher):
            raise TypeError("publisher must be an EventPublisher instance")

        processed = 0
        for stream_key in self._stream_keys:
            events = publisher.get_mock_events(stream_key)
            for event in events:
                handlers = self._handlers.get(event.event_type, [])
                for handler in handlers:
                    try:
                        await handler(event)
                        processed += 1
                    except (OSError, RuntimeError, ValueError) as exc:
                        logger.warning(
                            "consumer_mock_handler_failed",
                            event_type=event.event_type,
                            event_id=event.event_id,
                            error=str(exc),
                        )
        return processed
