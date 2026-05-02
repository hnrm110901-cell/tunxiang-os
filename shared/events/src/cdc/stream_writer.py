"""CDC Stream Writer -- CDC 变更事件 → Redis Stream 写入器

职责：
- 将 CDCChangeEvent 写入 Redis Stream，供消费者（projector/analytics）消费
- Redis 不可用时自动降级到内存队列（dev mode / fallback）
- 支持单条/批量写入

架构：
  CDCListener → CDCChangeEvent → CDCStreamWriter.publish() → Redis Stream
                                                       ↘ in-memory queue (fallback)

Redis Stream key 格式：{prefix}:{table_name}:changes
  例：cdc:orders:changes

写入时间戳作为消息 ID 的一部分，保证时间顺序可追溯。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_STREAM_LENGTH: int = 100_000  # 每个 stream 最大消息数
MAX_RETRIES: int = 3
BASE_RETRY_DELAY: float = 0.5  # 秒


class CDCStreamWriter:
    """CDC 事件 → Redis Stream 写入器。

    支持两种模式：
    - Redis 模式：写入 Redis Stream，支持消费者组
    - 内存模式（dev/fallback）：写入 deque，用于开发或无 Redis 环境

    Args:
        redis_url:     Redis 连接 URL。None 使用环境变量 REDIS_URL。
        stream_prefix: Stream key 前缀（默认 "cdc"）
        mock:          Mock 模式，仅使用内存队列

    Usage:
        writer = CDCStreamWriter()
        await writer.connect()
        msg_id = await writer.publish(event)
        await writer.close()
    """

    def __init__(
        self,
        redis_url: str | None = None,
        stream_prefix: str = "cdc",
        *,
        mock: bool = False,
    ) -> None:
        self._redis_url = redis_url or REDIS_URL
        self._stream_prefix = stream_prefix
        self._mock = mock
        self._redis: Optional[object] = None  # redis.asyncio.Redis (lazy init)
        # 内存队列：stream_key → deque[dict]
        self._in_memory: dict[str, deque[dict[str, str]]] = {}

    # ── 生命周期 ──

    async def connect(self) -> None:
        """连接到 Redis（或使用内存模式）。

        Redis 连接失败时自动切换为内存模式（不抛异常）。
        """
        if self._mock:
            logger.info("cdc_stream_writer_mock_mode")
            return

        if self._redis is not None:
            return

        try:
            import redis.asyncio as aioredis

            self._redis = await aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            )
            # 验证连接
            await self._redis.ping()
            logger.info("cdc_stream_writer_redis_connected", url=self._redis_url)
        except (OSError, RuntimeError, ImportError) as exc:
            logger.warning(
                "cdc_stream_writer_redis_unavailable",
                error=str(exc),
                mode="fallback_to_memory",
            )
            self._redis = None

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis is not None:
            try:
                await self._redis.aclose()  # type: ignore[union-attr]
            except (OSError, RuntimeError):
                pass
            self._redis = None
            logger.info("cdc_stream_writer_closed")

    # ── 发布 ──

    async def publish(self, event: "CDCChangeEvent") -> str:
        """发布单条 CDC 事件。

        Args:
            event: CDCChangeEvent 实例

        Returns:
            消息 ID（Redis stream entry ID 或 "mem:{seq}"）

        失败时自动降级到内存队列，不抛异常。
        """
        stream_key = f"{self._stream_prefix}:{event.table}:changes"
        data = event.model_dump_json()

        # 写入 Redis
        if self._redis is not None:
            msg_id = await self._publish_to_redis(stream_key, data)
            if msg_id is not None:
                return msg_id
            # Redis 写入失败，降级到内存
            logger.warning("cdc_stream_writer_redis_fallback", table=event.table)

        # 内存队列
        return self._publish_to_memory(stream_key, data)

    async def publish_batch(self, events: list["CDCChangeEvent"]) -> list[str]:
        """批量发布 CDC 事件（保序）。

        Args:
            events: CDCChangeEvent 列表

        Returns:
            消息 ID 列表（与输入一一对应）
        """
        results: list[str] = []
        for event in events:
            msg_id = await self.publish(event)
            results.append(msg_id)
        return results

    # ── 内部实现 ──

    async def _publish_to_redis(self, stream_key: str, data: str) -> Optional[str]:
        """带指数退避重试的 Redis 发布。"""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                msg_id = await self._redis.xadd(  # type: ignore[union-attr]
                    stream_key,
                    {"data": data, "ts": datetime.now(timezone.utc).isoformat()},
                    maxlen=MAX_STREAM_LENGTH,
                    approximate=True,
                )
                logger.debug(
                    "cdc_event_published",
                    stream_key=stream_key,
                    msg_id=msg_id,
                )
                return msg_id  # type: ignore[return-value]

            except (OSError, RuntimeError) as exc:
                logger.warning(
                    "cdc_redis_publish_retry",
                    attempt=attempt,
                    max_retries=MAX_RETRIES,
                    stream_key=stream_key,
                    error=str(exc),
                )
                self._redis = None  # 重置连接
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BASE_RETRY_DELAY * (2 ** (attempt - 1)))

        return None

    def _publish_to_memory(self, stream_key: str, data: str) -> str:
        """写入内存队列（dev/fallback）。"""
        if stream_key not in self._in_memory:
            self._in_memory[stream_key] = deque(maxlen=MAX_STREAM_LENGTH)
        seq = len(self._in_memory[stream_key]) + 1
        self._in_memory[stream_key].append({"data": data, "ts": datetime.now(timezone.utc).isoformat()})
        msg_id = f"mem:{seq}"
        logger.debug("cdc_event_published_memory", stream_key=stream_key, msg_id=msg_id)
        return msg_id

    # ── 查询（测试/调试用）──

    def get_memory_events(self, table_name: str | None = None) -> list[dict[str, str]]:
        """获取内存队列中的事件（仅内存模式有用）。

        Args:
            table_name: 过滤指定表。None 返回所有。

        Returns:
            事件字典列表
        """
        if table_name is not None:
            stream_key = f"{self._stream_prefix}:{table_name}:changes"
            return list(self._in_memory.get(stream_key, []))
        result: list[dict[str, str]] = []
        for q in self._in_memory.values():
            result.extend(q)
        return result

    def clear_memory(self) -> None:
        """清空内存队列。"""
        self._in_memory.clear()
