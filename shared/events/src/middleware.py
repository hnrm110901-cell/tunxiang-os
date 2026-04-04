"""事件中间件 -- 日志、租户隔离、去重

中间件是事件处理器的包装层，在 handler 执行前后插入横切关注点。
用法：
    consumer.subscribe("order.created", logging_mw(tenant_mw(dedup_mw(my_handler))))

或者使用 apply_middleware 辅助函数一次性组合多个中间件：
    wrapped = apply_middleware(my_handler, [LoggingMiddleware(), TenantIsolationMiddleware("t1"), DeduplicationMiddleware()])
    consumer.subscribe("order.created", wrapped)
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Awaitable, Callable

import structlog

from .event_base import TxEvent

logger = structlog.get_logger(__name__)

EventHandler = Callable[[TxEvent], Awaitable[None]]


class EventMiddleware(ABC):
    """中间件基类"""

    @abstractmethod
    def wrap(self, handler: EventHandler) -> EventHandler:
        """包装一个事件处理器，返回新的处理器。"""
        ...


# ------------------------------------------------------------------
# 日志中间件
# ------------------------------------------------------------------


class LoggingMiddleware(EventMiddleware):
    """自动记录每个事件的发布和消费。"""

    def wrap(self, handler: EventHandler) -> EventHandler:
        async def _wrapped(event: TxEvent) -> None:
            start = time.monotonic()
            logger.info(
                "middleware_event_received",
                event_type=event.event_type,
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                source=event.source,
            )
            try:
                await handler(event)
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "middleware_event_handled",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    elapsed_ms=round(elapsed_ms, 2),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.error(
                    "middleware_event_handler_failed",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    elapsed_ms=round(elapsed_ms, 2),
                    error=str(exc),
                    exc_info=True,
                )
                raise

        return _wrapped


# ------------------------------------------------------------------
# 租户隔离中间件
# ------------------------------------------------------------------


class TenantIsolationMiddleware(EventMiddleware):
    """确保事件只被同一 tenant 的消费者处理。

    Args:
        allowed_tenant_id: 当前服务/实例允许处理的 tenant_id。
                           传 None 表示不做租户过滤（兼容测试场景）。
    """

    def __init__(self, allowed_tenant_id: str | None = None) -> None:
        self._allowed_tenant_id = allowed_tenant_id

    def wrap(self, handler: EventHandler) -> EventHandler:
        allowed = self._allowed_tenant_id

        async def _wrapped(event: TxEvent) -> None:
            if allowed is not None and event.tenant_id != allowed:
                logger.debug(
                    "middleware_tenant_filtered",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    event_tenant=event.tenant_id,
                    allowed_tenant=allowed,
                )
                return  # 静默跳过，不是本租户的事件

            await handler(event)

        return _wrapped


# ------------------------------------------------------------------
# 重复检测中间件
# ------------------------------------------------------------------


class DeduplicationMiddleware(EventMiddleware):
    """基于 event_id 的幂等去重。

    使用 LRU 策略维护最近 N 个已处理的 event_id。
    重复事件静默跳过。

    Args:
        max_size: LRU 缓存容量（默认 10000）
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self._max_size = max_size
        # OrderedDict 作为 LRU：key = event_id, value = None
        self._seen: OrderedDict[str, None] = OrderedDict()

    def wrap(self, handler: EventHandler) -> EventHandler:
        seen = self._seen
        max_size = self._max_size

        async def _wrapped(event: TxEvent) -> None:
            if event.event_id in seen:
                logger.debug(
                    "middleware_dedup_skipped",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )
                return

            await handler(event)

            # 记录已处理
            seen[event.event_id] = None
            seen.move_to_end(event.event_id)
            # LRU 淘汰
            while len(seen) > max_size:
                seen.popitem(last=False)

        return _wrapped


# ------------------------------------------------------------------
# 辅助函数：组合多个中间件
# ------------------------------------------------------------------


def apply_middleware(
    handler: EventHandler,
    middlewares: list[EventMiddleware],
) -> EventHandler:
    """将多个中间件依次包装到 handler 上。

    中间件按列表顺序从外到内包装，即列表第一个中间件最先执行。

    Args:
        handler:     原始事件处理器
        middlewares: 中间件列表

    Returns:
        包装后的事件处理器
    """
    wrapped = handler
    for mw in reversed(middlewares):
        wrapped = mw.wrap(wrapped)
    return wrapped
