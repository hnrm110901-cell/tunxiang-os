"""EventPublisher -- Redis Streams 统一事件发布器

特性：
- 单条 / 批量发布
- 失败重试（3 次，指数退避）
- Mock 模式（不依赖真实 Redis，用内存队列）
- Redis 不可用时自动降级（不影响主业务流程）
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from typing import Optional, Sequence

import structlog

from .event_base import TxEvent
from .event_types import resolve_stream_key

logger = structlog.get_logger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_STREAM_LENGTH: int = 100_000
MAX_RETRIES: int = 3
BASE_RETRY_DELAY: float = 0.5  # 秒


class EventPublisher:
    """Redis Streams 事件发布器

    Args:
        redis_url: Redis 连接 URL。传 None 使用环境变量 REDIS_URL。
        mock:      为 True 时启用 Mock 模式，事件写入内存队列而非 Redis。
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        mock: bool = False,
    ) -> None:
        self._redis_url = redis_url or REDIS_URL
        self._mock = mock
        self._redis: Optional[object] = None  # aioredis.Redis (lazy init)
        # Mock 模式下的内存队列：stream_key -> deque[TxEvent]
        self._mock_queues: dict[str, deque[TxEvent]] = {}

    # ------------------------------------------------------------------
    # Redis 连接管理
    # ------------------------------------------------------------------

    async def _get_redis(self) -> object:
        """延迟获取 Redis 连接单例。"""
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = await aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return self._redis

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[union-attr]
            self._redis = None
            logger.info("event_publisher_closed")

    # ------------------------------------------------------------------
    # 发布
    # ------------------------------------------------------------------

    async def publish(self, event: TxEvent) -> str | None:
        """发布单条事件。

        Returns:
            Redis Stream entry ID（如 "1699000000000-0"）。
            Mock 模式返回 "mock-{event_id}"。
            失败（重试耗尽）返回 None。
        """
        stream_key = resolve_stream_key(event.event_type)

        if self._mock:
            return self._mock_publish(stream_key, event)

        return await self._publish_with_retry(stream_key, event)

    async def publish_batch(self, events: Sequence[TxEvent]) -> list[str | None]:
        """批量发布事件。

        按事件顺序逐条发布（保序），返回每条的 entry ID。
        某条失败不影响后续发布。
        """
        results: list[str | None] = []
        for event in events:
            entry_id = await self.publish(event)
            results.append(entry_id)
        return results

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _publish_with_retry(self, stream_key: str, event: TxEvent) -> str | None:
        """带指数退避重试的发布。"""
        fields = event.to_stream_fields()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                redis = await self._get_redis()
                entry_id: str = await redis.xadd(  # type: ignore[union-attr]
                    stream_key,
                    fields,
                    maxlen=MAX_STREAM_LENGTH,
                    approximate=True,
                )
                logger.info(
                    "event_published",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    stream_key=stream_key,
                    tenant_id=event.tenant_id,
                    entry_id=entry_id,
                    source=event.source,
                )
                return entry_id

            except OSError as exc:
                # 网络层失败 — 重置连接
                logger.warning(
                    "event_publish_retry",
                    attempt=attempt,
                    max_retries=MAX_RETRIES,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    error=str(exc),
                )
                self._redis = None
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BASE_RETRY_DELAY * (2 ** (attempt - 1)))

            except RuntimeError as exc:
                # Redis 协议层异常
                logger.warning(
                    "event_publish_retry",
                    attempt=attempt,
                    max_retries=MAX_RETRIES,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    error=str(exc),
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BASE_RETRY_DELAY * (2 ** (attempt - 1)))

        # 重试耗尽
        logger.error(
            "event_publish_exhausted",
            event_type=event.event_type,
            event_id=event.event_id,
            stream_key=stream_key,
            tenant_id=event.tenant_id,
        )
        return None

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------

    def _mock_publish(self, stream_key: str, event: TxEvent) -> str:
        """Mock 发布 -- 写入内存队列。"""
        if stream_key not in self._mock_queues:
            self._mock_queues[stream_key] = deque(maxlen=MAX_STREAM_LENGTH)
        self._mock_queues[stream_key].append(event)
        mock_id = f"mock-{event.event_id}"
        logger.debug(
            "event_published_mock",
            event_type=event.event_type,
            event_id=event.event_id,
            stream_key=stream_key,
        )
        return mock_id

    def get_mock_events(self, stream_key: str | None = None) -> list[TxEvent]:
        """获取 Mock 模式下发布的事件（测试用）。

        Args:
            stream_key: 指定 stream key 过滤。None 返回全部。
        """
        if stream_key is not None:
            return list(self._mock_queues.get(stream_key, []))
        result: list[TxEvent] = []
        for q in self._mock_queues.values():
            result.extend(q)
        return result

    def clear_mock(self) -> None:
        """清空 Mock 队列。"""
        self._mock_queues.clear()
