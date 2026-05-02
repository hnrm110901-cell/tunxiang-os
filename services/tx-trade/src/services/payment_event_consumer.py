"""支付事件消费者 — tx-trade 消费 tx-pay 的 payment.confirmed / payment.refunded 事件

Task 1.2: 关闭 P0-02 风险 — 支付成功 3 秒内驱动订单状态。

架构：
  tx-pay 发射 payment.confirmed → Redis Stream → tx-trade EventConsumer
  → 查找订单(stream_id=order_id) → 更新 order.status + payment.status → 提交

幂等性：
  - 通过 payment_id + event_id 去重
  - 订单已是 completed 状态 → 直接 ACK
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.events.src.consumer import EventConsumer
from shared.events.src.event_base import TxEvent
from shared.events.src.event_types import PaymentEventType
from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

# 支付状态常量
PAYMENT_STATUS_SUCCESS = "success"
PAYMENT_STATUS_REFUNDED = "refunded"
PAYMENT_STATUS_PARTIAL_REFUND = "partial_refund"

ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_CANCELLED = "cancelled"

# EventConsumer 组名 — 确保 tx-trade 集群内只有一个实例消费同一事件
CONSUMER_GROUP = "tx-trade-payment-consumer"


def _make_consumer_name() -> str:
    return f"tx-trade-payment-{uuid.uuid4().hex[:8]}"


class PaymentEventHandlers:
    """支付事件处理器 — 数据库操作用独立 session"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def handle_payment_confirmed(self, event: TxEvent) -> None:
        """处理 payment.confirmed 事件：更新订单状态为已完成"""
        payment_id = event.data.get("payment_id")
        order_id = event.stream_id
        amount_fen = event.data.get("amount_fen", 0)
        tenant_id = event.tenant_id or ""

        if not order_id:
            logger.warning(
                "payment_event_no_stream_id",
                event_type=event.event_type,
                event_id=event.event_id,
            )
            return

        async with self._session_factory() as db:
            try:
                async with db.begin():
                    # 1. 更新 orders 表状态
                    result = await db.execute(
                        text(
                            """UPDATE orders
                               SET status = :new_status,
                                   final_amount_fen = COALESCE(final_amount_fen, :amount_fen),
                                   completed_at = COALESCE(completed_at, :now)
                               WHERE id = :order_id
                                 AND status NOT IN (:completed, :cancelled)
                               RETURNING id, order_no"""
                        ),
                        {
                            "new_status": ORDER_STATUS_COMPLETED,
                            "amount_fen": amount_fen,
                            "now": datetime.now(timezone.utc),
                            "order_id": order_id,
                            "completed": ORDER_STATUS_COMPLETED,
                            "cancelled": ORDER_STATUS_CANCELLED,
                        },
                    )
                    updated_order: Optional[tuple] = result.fetchone()

                    if updated_order is None:
                        logger.debug(
                            "payment_event_order_skip",
                            order_id=order_id,
                            reason="already_completed_or_cancelled_or_not_found",
                            event_id=event.event_id,
                        )
                        return

                    # 2. 更新 payments 表状态（如果存在）
                    await db.execute(
                        text(
                            """UPDATE payments
                               SET status = :new_status,
                                   trade_no = COALESCE(trade_no, :trade_no),
                                   paid_at = COALESCE(paid_at, :now)
                               WHERE payment_no = :payment_id
                                 AND status != :success_status"""
                        ),
                        {
                            "new_status": PAYMENT_STATUS_SUCCESS,
                            "trade_no": event.data.get("trade_no", ""),
                            "now": datetime.now(timezone.utc),
                            "payment_id": payment_id,
                            "success_status": PAYMENT_STATUS_SUCCESS,
                        },
                    )

                    logger.info(
                        "payment_confirmed_order_updated",
                        order_id=order_id,
                        order_no=updated_order[1] if updated_order else "?",
                        payment_id=payment_id,
                        event_id=event.event_id,
                        source_service=event.source,
                    )

            except Exception:
                logger.error(
                    "payment_event_handler_error",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    order_id=order_id,
                    payment_id=payment_id,
                    exc_info=True,
                )
                raise

    async def handle_payment_refunded(self, event: TxEvent) -> None:
        """处理 payment.refunded 事件：更新订单退款状态"""
        payment_id = event.data.get("payment_id")
        refund_id = event.data.get("refund_id")
        order_id = event.stream_id
        refund_amount_fen = event.data.get("amount_fen", 0)

        if not order_id:
            logger.warning(
                "refund_event_no_stream_id",
                event_type=event.event_type,
                event_id=event.event_id,
            )
            return

        async with self._session_factory() as db:
            try:
                async with db.begin():
                    # 1. 查询原始支付金额以判断全额/部分退款
                    result = await db.execute(
                        text(
                            """SELECT amount_fen FROM payments
                               WHERE payment_no = :payment_id"""
                        ),
                        {"payment_id": payment_id},
                    )
                    row = result.fetchone()
                    if not row:
                        logger.error(
                            "refund_event_payment_not_found",
                            payment_id=payment_id,
                            order_id=order_id,
                            event_id=event.event_id,
                        )
                        return
                    original_amount = row[0]

                    is_full_refund = original_amount > 0 and refund_amount_fen >= original_amount

                    # 2. 更新 orders 表退款状态
                    new_order_status = ORDER_STATUS_CANCELLED if is_full_refund else ORDER_STATUS_COMPLETED
                    refund_status = "full" if is_full_refund else "partial"

                    await db.execute(
                        text(
                            """UPDATE orders
                               SET status = :new_status,
                                   refund_status = :refund_status
                               WHERE id = :order_id"""
                        ),
                        {
                            "new_status": new_order_status,
                            "refund_status": refund_status,
                            "order_id": order_id,
                        },
                    )

                    # 3. 更新 payments 表退款状态
                    await db.execute(
                        text(
                            """UPDATE payments
                               SET status = :new_status
                               WHERE payment_no = :payment_id"""
                        ),
                        {
                            "new_status": (
                                PAYMENT_STATUS_REFUNDED
                                if is_full_refund
                                else PAYMENT_STATUS_PARTIAL_REFUND
                            ),
                            "payment_id": payment_id,
                        },
                    )

                    logger.info(
                        "payment_refunded_order_updated",
                        order_id=order_id,
                        payment_id=payment_id,
                        refund_id=refund_id,
                        is_full_refund=is_full_refund,
                        event_id=event.event_id,
                        source_service=event.source,
                    )

            except Exception:
                logger.error(
                    "refund_event_handler_error",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    order_id=order_id,
                    payment_id=payment_id,
                    exc_info=True,
                )
                raise


def create_payment_event_consumer(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> EventConsumer:
    """创建支付事件消费者 — 在 tx-trade lifespan 中启动。

    Args:
        session_factory: 数据库 session 工厂。None 使用默认 async_session_factory。
    """
    sf = session_factory or async_session_factory
    handlers = PaymentEventHandlers(sf)

    consumer = EventConsumer(
        group_name=CONSUMER_GROUP,
        consumer_name=_make_consumer_name(),
    )

    # 订阅支付事件
    consumer.subscribe(PaymentEventType.CONFIRMED.value, handlers.handle_payment_confirmed)
    consumer.subscribe(PaymentEventType.REFUNDED.value, handlers.handle_payment_refunded)

    logger.info(
        "payment_event_consumer_created",
        group=CONSUMER_GROUP,
        subscriptions=[
            PaymentEventType.CONFIRMED.value,
            PaymentEventType.REFUNDED.value,
        ],
    )

    return consumer


async def start_payment_event_consumer(
    consumer: EventConsumer,
    session_factory: async_sessionfactory[AsyncSession] | None = None,
) -> asyncio.Task:
    """在后台 task 中启动支付事件消费者。

    Returns:
        asyncio.Task: 可被 cancel() 和 await 的消费者 task。
    """
    return asyncio.create_task(consumer.start(batch_size=10, block_ms=2000))
