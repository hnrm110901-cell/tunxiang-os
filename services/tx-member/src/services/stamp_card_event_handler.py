"""集点卡 — 订单完成事件处理器

监听 trade.order.paid 事件，自动触发集点卡盖章。

事件链路：
  tx-trade 发布 ORDER_PAID → Redis Stream → tx-member 消费
  → stamp_card_service.auto_stamp() → 检查活跃集点卡 → 盖章 → 集满发奖

本模块提供事件处理函数，由 tx-member 的事件消费器调用。
"""
from __future__ import annotations

from typing import Any, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .stamp_card_service import auto_stamp

logger = structlog.get_logger(__name__)


async def handle_order_paid(
    event_data: dict[str, Any],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """处理订单支付完成事件 — 触发自动盖章

    Args:
        event_data: 事件数据，至少包含:
            - customer_id: str
            - order_id: str
            - order_total_fen: int
            - store_id: str
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"stamped": bool, "stamp_results": [...]}
    """
    customer_id = event_data.get("customer_id")
    order_id = event_data.get("order_id")
    order_total_fen = event_data.get("order_total_fen", 0)
    store_id = event_data.get("store_id")

    if not customer_id or not order_id:
        logger.warning(
            "stamp_card_event.missing_fields",
            event_data=event_data,
        )
        return {"stamped": False, "error": "missing_customer_or_order"}

    logger.info(
        "stamp_card_event.processing",
        customer_id=customer_id,
        order_id=order_id,
        order_total_fen=order_total_fen,
    )

    result = await auto_stamp(
        customer_id=customer_id,
        order_id=order_id,
        order_total_fen=order_total_fen,
        store_id=store_id or "",
        tenant_id=tenant_id,
        db=db,
    )

    if result.get("stamps_added", 0) > 0:
        logger.info(
            "stamp_card_event.stamped",
            customer_id=customer_id,
            stamps_added=result["stamps_added"],
            cards_completed=result.get("cards_completed", 0),
        )

    return {
        "stamped": result.get("stamps_added", 0) > 0,
        "stamp_results": result,
    }


async def register_stamp_card_consumer(
    session_factory: Callable,
    redis_url: str = "redis://localhost:6379",
) -> None:
    """注册 Redis Stream 消费者

    生产环境：由 tx-member main.py lifespan 调用。
    监听 trade_events stream 中的 ORDER_PAID 事件。
    """
    import asyncio

    logger.info("stamp_card_consumer.starting", stream="trade_events")

    while True:
        try:
            await asyncio.sleep(1)
            # TODO: 接入 Redis Stream 消费
            # async with aioredis.from_url(redis_url) as redis:
            #     events = await redis.xread({"trade_events": "$"}, count=10, block=5000)
            #     for stream, messages in events:
            #         for msg_id, data in messages:
            #             if data.get("event_type") == "trade.order.paid":
            #                 async with session_factory() as db:
            #                     async with db.begin():
            #                         await handle_order_paid(
            #                             json.loads(data["event_data"]),
            #                             data["tenant_id"],
            #                             db,
            #                         )
        except asyncio.CancelledError:
            logger.info("stamp_card_consumer.stopped")
            break
        except Exception:  # noqa: BLE001 — consumer top-level loop must not crash
            logger.exception("stamp_card_consumer.error", exc_info=True)
            await asyncio.sleep(5)
