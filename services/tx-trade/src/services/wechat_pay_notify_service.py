"""微信支付异步通知 — 落库 + 幂等 + 订单闭环（无 X-Tenant-ID 回调）"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType, PaymentEventType
from shared.ontology.src.database import get_db_no_rls, get_db_with_tenant
from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus

from ..models.enums import PaymentMethod, PaymentStatus
from ..models.payment import Payment

logger = structlog.get_logger()


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _amount_fen_from_decrypted(decrypted: dict[str, Any]) -> int:
    amt = decrypted.get("amount") or {}
    v = amt.get("payer_total")
    if v is None:
        v = amt.get("total")
    if v is None:
        return 0
    return int(v)


def _need_pay_fen(order: Order) -> int:
    if order.final_amount_fen is not None:
        return int(order.final_amount_fen)
    return int(order.total_amount_fen)


async def apply_wechat_pay_notify_success(decrypted: dict[str, Any]) -> dict[str, Any]:
    """处理微信回调解密后的成功通知。

    - 通过 ``out_trade_no``（= 预下单时的商户订单号，对应 ``orders.order_no`` 或 ``orders.id``）定位订单
    - 以 ``transaction_id`` 幂等：已存在同 ``trade_no`` 的支付则跳过
    - 足额后订单置为 ``completed`` 并旁路事件

    Returns:
        含 ``ok``、``duplicate``、``order_id``、``message`` 等，供路由打日志；找不到订单仍 ``ok`` 以免微信无限重试。
    """
    out_trade_no = (decrypted.get("out_trade_no") or "").strip()
    transaction_id = (decrypted.get("transaction_id") or "").strip()
    if not out_trade_no or not transaction_id:
        logger.warning("wechat_notify_missing_fields", keys=list(decrypted.keys()))
        return {"ok": False, "message": "missing_out_trade_no_or_transaction_id"}

    amount_fen = _amount_fen_from_decrypted(decrypted)
    if amount_fen <= 0:
        logger.warning("wechat_notify_invalid_amount", out_trade_no=out_trade_no)
        return {"ok": False, "message": "invalid_amount"}

    order_snapshot: dict[str, Any] | None = None

    async for session in get_db_no_rls():
        conds = [Order.order_no == out_trade_no]
        if _is_uuid(out_trade_no):
            conds.append(Order.id == uuid.UUID(out_trade_no))
        stmt = select(Order).where(or_(*conds)).limit(1)
        res = await session.execute(stmt)
        order = res.scalar_one_or_none()
        if order is None:
            logger.warning("wechat_notify_order_not_found", out_trade_no=out_trade_no)
            return {"ok": True, "message": "order_not_found", "order_id": None}

        order_snapshot = {
            "id": order.id,
            "tenant_id": order.tenant_id,
            "order_no": order.order_no,
            "status": order.status,
            "final_amount_fen": order.final_amount_fen,
            "total_amount_fen": order.total_amount_fen,
            "store_id": order.store_id,
            "customer_id": order.customer_id,
            "table_number": order.table_number,
            "discount_amount_fen": order.discount_amount_fen,
        }

    assert order_snapshot is not None

    if order_snapshot["status"] == "cancelled":
        logger.warning(
            "wechat_notify_order_cancelled",
            order_id=str(order_snapshot["id"]),
            out_trade_no=out_trade_no,
        )
        return {"ok": True, "message": "order_cancelled_skip", "order_id": str(order_snapshot["id"])}

    tenant_id_str = str(order_snapshot["tenant_id"])
    order_uuid = order_snapshot["id"]

    inner: dict[str, Any] = {"duplicate": False}
    async for db in get_db_with_tenant(tenant_id_str):
        inner = await _apply_payment_and_maybe_complete(
            db=db,
            order_uuid=order_uuid,
            tenant_id_str=tenant_id_str,
            transaction_id=transaction_id,
            amount_fen=amount_fen,
            order_snapshot=order_snapshot,
        )

    return {
        "ok": True,
        "message": "duplicate" if inner.get("duplicate") else "applied",
        "duplicate": bool(inner.get("duplicate")),
        "order_id": str(order_uuid),
        "transaction_id": transaction_id,
    }


async def _apply_payment_and_maybe_complete(
    db: AsyncSession,
    order_uuid: uuid.UUID,
    tenant_id_str: str,
    transaction_id: str,
    amount_fen: int,
    order_snapshot: dict[str, Any],
) -> dict[str, Any]:
    res = await db.execute(
        select(Order).where(Order.id == order_uuid).with_for_update()
    )
    order = res.scalar_one()

    dup = await db.execute(
        select(Payment.id).where(
            Payment.order_id == order_uuid,
            Payment.trade_no == transaction_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        logger.info(
            "wechat_notify_duplicate",
            order_id=str(order_uuid),
            transaction_id=transaction_id,
        )
        return {"duplicate": True}

    need = _need_pay_fen(order)
    sum_res = await db.execute(
        select(func.coalesce(func.sum(Payment.amount_fen), 0)).where(
            Payment.order_id == order_uuid,
            Payment.status == PaymentStatus.paid.value,
        )
    )
    already_paid = int(sum_res.scalar_one() or 0)

    payment_no = f"WX-{transaction_id}"[:64]

    pay = Payment(
        id=uuid.uuid4(),
        tenant_id=order.tenant_id,
        order_id=order_uuid,
        payment_no=payment_no,
        method=PaymentMethod.wechat.value,
        amount_fen=amount_fen,
        status=PaymentStatus.paid.value,
        trade_no=transaction_id,
        paid_at=datetime.now(timezone.utc),
        payment_category="移动支付",
        extra={"channel": "wechat_jsapi", "out_trade_no": order.order_no},
    )
    db.add(pay)
    await db.flush()

    new_total = already_paid + amount_fen
    completed_now = False
    if need > 0 and new_total >= need:
        if order.status != OrderStatus.completed.value:
            order.status = OrderStatus.completed.value
            order.completed_at = datetime.now(timezone.utc)
            completed_now = True
        await db.flush()

    logger.info(
        "wechat_notify_payment_recorded",
        order_id=str(order_uuid),
        payment_no=payment_no,
        amount_fen=amount_fen,
        already_paid_before=already_paid,
        need_fen=need,
        new_total=new_total,
        completed_now=completed_now,
    )

    payment_record = {
        "payment_id": str(pay.id),
        "payment_no": payment_no,
        "method": PaymentMethod.wechat.value,
        "amount_fen": amount_fen,
        "trade_no": transaction_id,
    }

    asyncio.create_task(
        emit_event(
            event_type=PaymentEventType.CONFIRMED,
            tenant_id=tenant_id_str,
            stream_id=str(order_uuid),
            payload={
                "order_no": order_snapshot["order_no"],
                "amount_fen": amount_fen,
                "payment_records": [payment_record],
                "channel": "wechat",
                "transaction_id": transaction_id,
            },
            store_id=str(order_snapshot["store_id"]) if order_snapshot.get("store_id") else None,
            source_service="tx-trade",
            metadata={"trigger": "wechat_pay.notify"},
        )
    )

    if completed_now:
        asyncio.create_task(
            emit_event(
                event_type=OrderEventType.PAID,
                tenant_id=tenant_id_str,
                stream_id=str(order_uuid),
                payload={
                    "order_no": order_snapshot["order_no"],
                    "final_amount_fen": order.final_amount_fen,
                    "discount_amount_fen": order_snapshot.get("discount_amount_fen"),
                    "total_amount_fen": order.total_amount_fen,
                    "payment_methods": [PaymentMethod.wechat.value],
                    "customer_id": str(order.customer_id) if order.customer_id else None,
                    "table_number": order.table_number,
                    "change_fen": 0,
                },
                store_id=str(order_snapshot["store_id"]) if order_snapshot.get("store_id") else None,
                source_service="tx-trade",
                metadata={"trigger": "wechat_pay.notify"},
            )
        )

    return {"duplicate": False}
