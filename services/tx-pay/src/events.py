"""支付事件发射器 — 统一事件总线集成

所有支付状态变更通过本模块发射事件。
下游消费者（tx-finance/tx-ops/Agent）监听这些事件。
"""

from __future__ import annotations

import asyncio

import structlog

from .channels.base import CallbackPayload

logger = structlog.get_logger(__name__)


async def emit_payment_confirmed(payload: CallbackPayload) -> None:
    """发射支付确认事件（回调验证成功后）"""
    try:
        from shared.events.src.emitter import emit_event
        from shared.events.src.event_types import PaymentEventType

        asyncio.create_task(
            emit_event(
                event_type=PaymentEventType.CONFIRMED,
                tenant_id="",  # 回调中可能无 tenant_id，由 payment_id 关联
                stream_id=payload.payment_id,
                payload={
                    "payment_id": payload.payment_id,
                    "trade_no": payload.trade_no,
                    "amount_fen": payload.amount_fen,
                    "status": payload.status.value,
                },
                source_service="tx-pay",
            )
        )
        logger.info("payment_confirmed_event_emitted", payment_id=payload.payment_id)
    except ImportError:
        logger.debug("event_emitter_not_available")


async def emit_payment_refunded(
    payment_id: str,
    refund_id: str,
    amount_fen: int,
    tenant_id: str = "",
) -> None:
    """发射退款事件"""
    try:
        from shared.events.src.emitter import emit_event
        from shared.events.src.event_types import PaymentEventType

        asyncio.create_task(
            emit_event(
                event_type=PaymentEventType.REFUNDED,
                tenant_id=tenant_id,
                stream_id=payment_id,
                payload={
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                    "amount_fen": amount_fen,
                },
                source_service="tx-pay",
            )
        )
    except ImportError:
        logger.debug("event_emitter_not_available")
