"""PG LISTEN/NOTIFY 桥接 -- 用于实时性要求高的场景

典型用途：桌台状态变更、KDS 出餐通知等需要亚秒级延迟的场景。
Redis Streams 适合可靠投递 + 重放，PG NOTIFY 适合实时推送。
两者互补，不替代。

注意：PG NOTIFY payload 最大 8000 字节。超大 payload 应通过
Redis Streams 传输，PG NOTIFY 仅发送事件 ID 作为通知信号。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Awaitable, Callable, Optional

import structlog

from .event_base import TxEvent

logger = structlog.get_logger(__name__)

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# PG NOTIFY 处理器类型
NotifyHandler = Callable[[str, TxEvent], Awaitable[None]]


class PgNotifier:
    """PG NOTIFY 发送器

    Args:
        dsn: PostgreSQL 连接字符串。None 使用环境变量 DATABASE_URL。
        mock: Mock 模式，不连接真实 PG。
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        mock: bool = False,
    ) -> None:
        self._dsn = dsn or DATABASE_URL
        self._mock = mock
        self._pool: Optional[object] = None  # asyncpg.Pool
        # Mock 模式下的通知记录
        self._mock_notifications: list[tuple[str, str]] = []  # (channel, payload_json)

    async def _get_pool(self) -> object:
        """延迟获取连接池。"""
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=1,
                max_size=3,
                command_timeout=5,
            )
        return self._pool

    async def notify(self, channel: str, event: TxEvent) -> None:
        """发送 PG NOTIFY。

        Args:
            channel: PG 通知频道名，如 "table_status", "kds_ready"
            event:   要发送的事件

        Raises:
            asyncpg.PostgresError: PG 执行失败（非 Mock 模式）
        """
        payload_json = event.to_json()

        if len(payload_json.encode("utf-8")) > 7900:
            logger.warning(
                "pg_notify_payload_too_large",
                channel=channel,
                event_id=event.event_id,
                size=len(payload_json.encode("utf-8")),
                note="Truncating to event_id only. Use Redis Streams for full payload.",
            )
            # 降级：只发 event_id，消费者自行从 Redis Stream 拉取完整事件
            payload_json = json.dumps(
                {"event_id": event.event_id, "event_type": event.event_type},
                ensure_ascii=False,
            )

        if self._mock:
            self._mock_notifications.append((channel, payload_json))
            logger.debug(
                "pg_notify_mock",
                channel=channel,
                event_id=event.event_id,
            )
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(
                "SELECT pg_notify($1, $2)",
                channel,
                payload_json,
            )

        logger.info(
            "pg_notify_sent",
            channel=channel,
            event_type=event.event_type,
            event_id=event.event_id,
            tenant_id=event.tenant_id,
        )

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool is not None:
            await self._pool.close()  # type: ignore[union-attr]
            self._pool = None

    def get_mock_notifications(self) -> list[tuple[str, str]]:
        """获取 Mock 模式下的通知记录。"""
        return list(self._mock_notifications)

    def clear_mock(self) -> None:
        """清空 Mock 通知记录。"""
        self._mock_notifications.clear()


class PgListener:
    """PG LISTEN 监听器

    Args:
        dsn: PostgreSQL 连接字符串。None 使用环境变量 DATABASE_URL。
        mock: Mock 模式，不连接真实 PG。
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        mock: bool = False,
    ) -> None:
        self._dsn = dsn or DATABASE_URL
        self._mock = mock
        self._conn: Optional[object] = None  # asyncpg.Connection
        self._running = False
        # channel -> list[handler]
        self._handlers: dict[str, list[NotifyHandler]] = {}

    def listen(self, channel: str, handler: NotifyHandler) -> None:
        """注册通知处理器。

        Args:
            channel: PG 通知频道名
            handler: 异步处理函数，接收 (channel, TxEvent)
        """
        if channel not in self._handlers:
            self._handlers[channel] = []
        self._handlers[channel].append(handler)
        logger.info(
            "pg_listener_handler_registered",
            channel=channel,
        )

    async def start(self) -> None:
        """开始监听（阻塞式循环，应在独立 asyncio Task 中运行）。"""
        if self._mock:
            logger.info("pg_listener_mock_mode")
            return

        if not self._handlers:
            logger.warning("pg_listener_no_channels")
            return

        import asyncpg

        self._conn = await asyncpg.connect(self._dsn, timeout=5)
        self._running = True

        for channel in self._handlers:
            await self._conn.add_listener(channel, self._on_notification)  # type: ignore[union-attr]
            logger.info("pg_listener_subscribed", channel=channel)

        logger.info(
            "pg_listener_started",
            channels=sorted(self._handlers.keys()),
        )

        # 保持连接活跃，等待停止信号
        while self._running:
            await asyncio.sleep(1)

    def _on_notification(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """asyncpg 回调（同步），将处理分派到 asyncio 事件循环。"""
        loop = asyncio.get_event_loop()
        loop.create_task(self._dispatch(channel, payload))

    async def _dispatch(self, channel: str, payload: str) -> None:
        """反序列化并分发通知给注册的 handler。"""
        try:
            event = TxEvent.from_json(payload)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(
                "pg_listener_deserialize_failed",
                channel=channel,
                payload_preview=payload[:200],
                error=str(exc),
                exc_info=True,
            )
            return

        handlers = self._handlers.get(channel, [])
        for handler in handlers:
            try:
                await handler(channel, event)
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error(
                    "pg_listener_handler_failed",
                    channel=channel,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    error=str(exc),
                    exc_info=True,
                )

    async def stop(self) -> None:
        """优雅关闭监听器。"""
        self._running = False
        if self._conn is not None:
            for channel in self._handlers:
                try:
                    await self._conn.remove_listener(channel, self._on_notification)  # type: ignore[union-attr]
                except (OSError, RuntimeError):
                    pass  # 连接可能已断开
            await self._conn.close()  # type: ignore[union-attr]
            self._conn = None
        logger.info("pg_listener_stopped")

    async def inject_mock(self, channel: str, event: TxEvent) -> None:
        """Mock 模式下模拟接收通知（测试用）。

        Args:
            channel: 频道名
            event:   模拟事件
        """
        if not self._mock:
            raise RuntimeError("inject_mock() only works in mock mode")
        await self._dispatch(channel, event.to_json())
