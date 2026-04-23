"""emit_event — 平行事件发射器

Phase 1 核心机制：在现有服务写入路径"旁路"写入事件，零侵入。

使用方式一：asyncio.create_task（推荐，完全不阻塞主业务）
    import asyncio
    from shared.events.src.emitter import emit_event

    async def pay_order(order_id: UUID, tenant_id: UUID, ...):
        # 原有业务逻辑不变
        result = await order_repo.mark_paid(order_id, ...)

        # 旁路写入事件（create_task 不阻塞）
        asyncio.create_task(emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=str(order_id),
            payload={"total_fen": result.total_fen, "channel": "dine_in"},
            store_id=store_id,
            source_service="tx-trade",
        ))
        return result

使用方式二：await（需要确认写入成功时使用）
    event_id = await emit_event(...)

使用方式三：装饰器（自动从函数参数提取 tenant_id 等上下文）
    @emits(OrderEventType.PAID, source_service="tx-trade")
    async def pay_order(order_id, tenant_id, store_id, ...):
        ...
    # 函数执行完成后自动发射事件，payload 由返回值或 event_data 参数提供

设计决策：
- 同时写入 Redis Stream（实时推送）和 PG events 表（持久化）
- PG 写入失败不影响 Redis，Redis 失败不影响 PG
- 两个写入均异步降级，不抛异常，不影响主业务
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Optional
from uuid import UUID

import structlog

from .event_base import TxEvent
from .pg_event_store import PgEventStore
from .publisher import EventPublisher

logger = structlog.get_logger(__name__)

# 模块级 Redis 发布器单例（复用连接）
_redis_publisher: Optional[EventPublisher] = None


def _get_publisher() -> EventPublisher:
    global _redis_publisher
    if _redis_publisher is None:
        _redis_publisher = EventPublisher()
    return _redis_publisher


async def emit_event(
    *,
    event_type: object,
    tenant_id: UUID | str,
    stream_id: str,
    payload: dict[str, Any],
    store_id: Optional[UUID | str] = None,
    source_service: str = "unknown",
    metadata: Optional[dict[str, Any]] = None,
    causation_id: Optional[UUID | str] = None,
    correlation_id: Optional[UUID | str] = None,
) -> Optional[str]:
    """平行发射事件（同时写入 Redis Stream 和 PG events 表）。

    两个写入相互独立，任一失败不影响另一个，也不影响调用方。

    Args:
        event_type:      事件类型枚举或点分字符串
        tenant_id:       租户 UUID
        stream_id:       聚合根ID（如订单号、会员ID）
        payload:         业务数据（金额约定为分/整数）
        store_id:        门店 UUID（可选）
        source_service:  来源服务名（如 "tx-trade"）
        metadata:        元数据（设备/操作员/渠道等）
        causation_id:    触发本事件的父事件ID（因果链追踪）
        correlation_id:  同一业务流程的相关ID

    Returns:
        PG 写入的 event_id（UUID字符串），失败时返回 None。
    """
    event_type_str = (
        event_type.value  # type: ignore[union-attr]
        if hasattr(event_type, "value")
        else str(event_type)
    )

    # ── Redis Stream 写入（实时推送，投影器实时触发）──
    redis_task = asyncio.create_task(
        _publish_to_redis(
            event_type_str=event_type_str,
            tenant_id=tenant_id,
            stream_id=stream_id,
            payload=payload,
            store_id=store_id,
            source_service=source_service,
            metadata=metadata or {},
        )
    )

    # ── PG events 表写入（持久化，回溯/审计用）──
    event_id = await PgEventStore.append(
        event_type=event_type_str,
        tenant_id=tenant_id,
        stream_id=stream_id,
        payload=payload,
        store_id=store_id,
        source_service=source_service,
        metadata=metadata,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    # Redis 任务在后台完成，不等待
    redis_task.add_done_callback(_log_redis_result)

    return event_id


async def _publish_to_redis(
    *,
    event_type_str: str,
    tenant_id: UUID | str,
    stream_id: str,
    payload: dict[str, Any],
    store_id: Optional[UUID | str],
    source_service: str,
    metadata: dict[str, Any],
) -> None:
    """内部：发布到 Redis Stream（降级不抛异常）。"""
    try:
        publisher = _get_publisher()
        event = TxEvent(
            event_type=event_type_str,
            tenant_id=str(tenant_id),
            store_id=str(store_id) if store_id else None,
            payload={**payload, **{"_stream_id": stream_id, "_meta": metadata}},
            source=source_service,
        )
        await publisher.publish(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "emit_event_redis_failed",
            event_type=event_type_str,
            tenant_id=str(tenant_id),
            error=str(exc),
        )


def _log_redis_result(task: asyncio.Task) -> None:
    """Redis 任务完成回调，记录异常但不传播。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.warning("emit_event_redis_task_failed", error=str(exc))


# ──────────────────────────────────────────────────────────────────────
# 装饰器接口（可选，用于批量改造现有服务）
# ──────────────────────────────────────────────────────────────────────


def emits(
    event_type: object,
    *,
    source_service: str,
    extract_tenant_id: str = "tenant_id",
    extract_store_id: str = "store_id",
    extract_stream_id: Optional[str] = None,
    build_payload: Optional[Callable[..., dict]] = None,
) -> Callable:
    """装饰器：函数成功执行后自动发射事件。

    从被装饰函数的参数中提取 tenant_id / store_id，
    从返回值（或 build_payload 回调）构建 payload。

    Args:
        event_type:         事件类型枚举
        source_service:     来源服务名
        extract_tenant_id:  参数名（用于从 kwargs 提取 tenant_id）
        extract_store_id:   参数名（用于从 kwargs 提取 store_id）
        extract_stream_id:  参数名（用于从 kwargs 提取 stream_id；None 则用返回值的 id）
        build_payload:      (kwargs, result) -> dict，构建 payload；None 则用 result.__dict__

    Example:
        @emits(OrderEventType.PAID, source_service="tx-trade")
        async def pay_order(order_id: UUID, tenant_id: UUID, store_id: UUID, total_fen: int):
            ...
            return paid_order  # paid_order.id 会作为 stream_id
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)

            # 提取上下文
            tenant_id = kwargs.get(extract_tenant_id)
            if tenant_id is None:
                logger.warning(
                    "emits_decorator_missing_tenant_id",
                    func=func.__name__,
                    extract_tenant_id=extract_tenant_id,
                )
                return result

            store_id = kwargs.get(extract_store_id)

            if extract_stream_id:
                stream_id = str(kwargs.get(extract_stream_id, "unknown"))
            elif result is not None and hasattr(result, "id"):
                stream_id = str(result.id)
            else:
                stream_id = "unknown"

            # 构建 payload
            if build_payload:
                payload = build_payload(kwargs, result)
            elif result is not None and hasattr(result, "__dict__"):
                payload = {
                    k: str(v) if isinstance(v, UUID) else v for k, v in result.__dict__.items() if not k.startswith("_")
                }
            else:
                payload = {}

            asyncio.create_task(
                emit_event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    stream_id=stream_id,
                    payload=payload,
                    store_id=store_id,
                    source_service=source_service,
                )
            )
            return result

        return wrapper

    return decorator
