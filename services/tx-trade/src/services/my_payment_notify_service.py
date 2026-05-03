"""
Malaysia payment callback notification service.

Handles async callbacks from TnG eWallet, GrabPay, and Boost.
Pattern based on wechat_pay_notify_service.py.

Flow:
  1. Verify callback signature via the method-specific adapter
  2. Parse and validate callback payload
  3. Idempotency check (duplicate transaction_id)
  4. Record payment in payments table
  5. If order fully paid: mark as completed
  6. Emit PaymentEventType.CONFIRMED + OrderEventType.PAID events
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType, PaymentEventType
from shared.ontology.src.database import get_db_no_rls, get_db_with_tenant
from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus

from ..models.enums import PaymentStatus
from ..models.payment import Payment

logger = structlog.get_logger()


# ─── 回调签名验证器注册表 ─────────────────────────────────────────────────────────

# 允许注入 adapter 实例的外部 setter（由路由层在启动时注入）
# key = payment method name, value = adapter with verify_callback method
_VERIFIERS: dict[str, Any] = {}


def register_verifier(method: str, adapter: Any) -> None:
    """注册支付方式的回调签名验证器

    Args:
        method:  支付方式 (tng_ewallet / grabpay / boost)
        adapter: 适配器实例（必须实现 verify_callback(raw_body, signature) -> dict）
    """
    _VERIFIERS[method] = adapter
    logger.info("my_payment.verifier_registered", method=method)


def clear_verifiers() -> None:
    """清除所有注册的验证器（测试用）"""
    _VERIFIERS.clear()


# ─── 工具函数 ─────────────────────────────────────────────────────────────────────


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _need_pay_fen(order: Order) -> int:
    if order.final_amount_fen is not None:
        return int(order.final_amount_fen)
    return int(order.total_amount_fen)


def _resolve_payment_method(txn_type: str) -> str:
    """根据回调中识别出的交易类型返回屯象支付方式名

    Args:
        txn_type: 回调 payload 中的交易类型标识

    Returns:
        屯象内部支付方式名 (tng_ewallet / grabpay / boost)
    """
    method_map = {
        "tng": "tng_ewallet",
        "grabpay": "grabpay",
        "boost": "boost",
    }
    return method_map.get(txn_type, txn_type)


def _extract_txn_id(payload: dict, method: str) -> str:
    """从回调 payload 中提取对应支付方式的交易号

    Args:
        payload: 回调 payload 字典
        method:  支付方式 (tng_ewallet / grabpay / boost)

    Returns:
        交易号字符串
    """
    # Check provider-specific keys first
    provider_keys = {
        "tng_ewallet": ("tngTxnId", "tng_txn_id"),
        "grabpay": ("grabTxnId", "grab_txn_id"),
        "boost": ("boostTxnId", "boost_txn_id"),
    }
    keys = provider_keys.get(method, ("transactionId", "txn_id"))
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    # Fallback: try generic keys
    for generic_key in ("transactionId", "transaction_id", "txnId", "txn_id", "id"):
        value = payload.get(generic_key)
        if value:
            return str(value)
    return ""


def _extract_amount_fen(payload: dict, method: str) -> int:
    """从回调 payload 中提取支付金额（分）

    Args:
        payload: 回调 payload 字典
        method:  支付方式（仅用于日志）

    Returns:
        金额（分），提取失败返回 0
    """
    # Try several possible keys for amount
    raw = (
        payload.get("amount")
        or payload.get("totalAmount")
        or payload.get("total_amount")
        or payload.get("transactionAmount")
        or "0"
    )
    try:
        if isinstance(raw, (int, float)):
            return int(round(float(raw) * 100))  # Assume RM
        amount_str = str(raw).strip()
        if not amount_str:
            return 0
        return int(round(float(amount_str) * 100))  # RM → fen
    except (ValueError, TypeError):
        logger.warning(
            "my_payment.invalid_amount_in_callback",
            method=method,
            raw_value=raw,
        )
        return 0


def _extract_merchant_order_no(payload: dict) -> str:
    """从回调 payload 中提取商户订单号"""
    for key in ("merchantOrderNo", "merchant_order_no", "outTradeNo", "out_trade_no"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


# ─── 回调处理入口 ─────────────────────────────────────────────────────────────────


async def handle_my_payment_callback(
    method: str,
    raw_body: str,
    signature: str,
) -> dict[str, Any]:
    """处理马来西亚支付方式的异步回调通知

    统一入口，根据 method 分发到对应适配器的签名验证逻辑。
    验证通过后写入支付记录并更新订单状态。

    Args:
        method:    支付方式 (tng_ewallet / grabpay / boost)
        raw_body:  回调请求体原始字符串（JSON）
        signature: Header 中的签名字符串

    Returns:
        {"ok": bool, "message": str, "order_id": str|None, "duplicate": bool}

    注意：
        - 签名验证失败时返回 {"ok": False, "message": "signature_error"}
        - 即使订单找不到也返回 ok=True 以防止支付平台无限重试
    """
    verifier = _VERIFIERS.get(method)
    if not verifier:
        logger.error("my_payment.no_verifier_registered", method=method)
        return {"ok": False, "message": f"no_verifier_for_{method}"}

    if not raw_body or not signature:
        logger.warning("my_payment.missing_fields", method=method, has_body=bool(raw_body), has_sign=bool(signature))
        return {"ok": False, "message": "missing_body_or_signature"}

    # ── 1. 签名验证 ──────────────────────────────────────────────────────────────
    try:
        payload = verifier.verify_callback(raw_body=raw_body, signature=signature)
    except Exception as exc:
        logger.error("my_payment.verify_failed", method=method, error=str(exc))
        return {"ok": False, "message": "signature_verification_failed"}

    # ── 2. 提取关键字段 ──────────────────────────────────────────────────────────
    transaction_id = _extract_txn_id(payload, method)
    if not transaction_id:
        logger.warning("my_payment.no_transaction_id", method=method, payload_keys=list(payload.keys()))
        return {"ok": False, "message": "missing_transaction_id"}

    merchant_order_no = _extract_merchant_order_no(payload)
    amount_fen = _extract_amount_fen(payload, method)

    if amount_fen <= 0:
        logger.warning("my_payment.invalid_amount", method=method, transaction_id=transaction_id)
        return {"ok": False, "message": "invalid_amount"}

    # ── 3. 定位订单 ──────────────────────────────────────────────────────────────
    order_snapshot: dict[str, Any] | None = None

    async for session in get_db_no_rls():
        conds = [Order.order_no == merchant_order_no]
        if _is_uuid(merchant_order_no):
            conds.append(Order.id == uuid.UUID(merchant_order_no))
        stmt = select(Order).where(*conds).limit(1)
        res = await session.execute(stmt)
        order = res.scalar_one_or_none()
        if order is None:
            logger.warning(
                "my_payment.order_not_found",
                method=method,
                merchant_order_no=merchant_order_no,
                transaction_id=transaction_id,
            )
            return {"ok": True, "message": "order_not_found", "order_id": None}

        # If order has order_no, also try matching by order_no
        if order.order_no and order.order_no != merchant_order_no:
            pass  # Already matched by UUID or order_no

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
            "my_payment.order_cancelled",
            method=method,
            order_id=str(order_snapshot["id"]),
            transaction_id=transaction_id,
        )
        return {"ok": True, "message": "order_cancelled_skip", "order_id": str(order_snapshot["id"])}

    # ── 4. 写入支付并更新订单 ────────────────────────────────────────────────────
    tenant_id_str = str(order_snapshot["tenant_id"])
    order_uuid = order_snapshot["id"]

    inner: dict[str, Any] = {"duplicate": False}
    async for db in get_db_with_tenant(tenant_id_str):
        inner = await _apply_payment_and_maybe_complete(
            db=db,
            order_uuid=order_uuid,
            tenant_id_str=tenant_id_str,
            method=method,
            transaction_id=transaction_id,
            amount_fen=amount_fen,
            merchant_order_no=merchant_order_no,
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
    method: str,
    transaction_id: str,
    amount_fen: int,
    merchant_order_no: str,
    order_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """记录支付并（如果足额）完成订单

    Args:
        db:               带 tenant RLS 的 DB session
        order_uuid:       订单 UUID
        tenant_id_str:    租户 ID
        method:           支付方式
        transaction_id:   支付平台交易号（用于幂等检查）
        amount_fen:       支付金额（分）
        merchant_order_no: 商户订单号
        order_snapshot:   订单快照

    Returns:
        {"duplicate": bool} — True if this is a duplicate callback
    """
    # 行级锁保护并发
    res = await db.execute(select(Order).where(Order.id == order_uuid).with_for_update())
    order = res.scalar_one()

    # ── 幂等检查：同 transaction_id 是否已有支付 ────────────────────────────────
    dup = await db.execute(
        select(Payment.id).where(
            Payment.order_id == order_uuid,
            Payment.trade_no == transaction_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        logger.info(
            "my_payment.duplicate",
            method=method,
            order_id=str(order_uuid),
            transaction_id=transaction_id,
        )
        return {"duplicate": True}

    # ── 计算已付金额 ────────────────────────────────────────────────────────────
    need = _need_pay_fen(order)
    sum_res = await db.execute(
        select(func.coalesce(func.sum(Payment.amount_fen), 0)).where(
            Payment.order_id == order_uuid,
            Payment.status == PaymentStatus.paid.value,
        )
    )
    already_paid = int(sum_res.scalar_one() or 0)

    # ── 创建支付记录 ────────────────────────────────────────────────────────────
    # 先尝试查找已有的 pending 支付记录（由 create_payment 预创建的）
    payment_no = f"{method.upper()}-{transaction_id}"[:64]

    existing_pending = await db.execute(
        select(Payment).where(
            Payment.order_id == order_uuid,
            Payment.method == method,
            Payment.status == PaymentStatus.pending.value,
            Payment.amount_fen == amount_fen,
        ).limit(1)
    )
    existing_pay = existing_pending.scalar_one_or_none()

    if existing_pay:
        # 更新已有的 pending 记录为 paid
        existing_pay.status = PaymentStatus.paid.value
        existing_pay.trade_no = transaction_id
        existing_pay.paid_at = datetime.now(timezone.utc)
        existing_pay.payment_no = payment_no
        pay = existing_pay
    else:
        # 创建新支付记录（兜底：回调先于预创建到达，或没有预创建）
        pay = Payment(
            id=uuid.uuid4(),
            tenant_id=order.tenant_id,
            order_id=order_uuid,
            payment_no=payment_no,
            method=method,
            amount_fen=amount_fen,
            status=PaymentStatus.paid.value,
            trade_no=transaction_id,
            paid_at=datetime.now(timezone.utc),
            payment_category="移动支付",
            extra={
                "channel": method,
                "merchant_order_no": merchant_order_no,
                "callback_raw_transaction_id": transaction_id,
            },
        )
        db.add(pay)

    await db.flush()

    # ── 判断是否足额，足额则完成订单 ────────────────────────────────────────────
    new_total = already_paid + amount_fen
    completed_now = False
    if need > 0 and new_total >= need:
        if order.status != OrderStatus.completed.value:
            order.status = OrderStatus.completed.value
            order.completed_at = datetime.now(timezone.utc)
            completed_now = True
        await db.flush()

    logger.info(
        "my_payment.payment_recorded",
        method=method,
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
        "method": method,
        "amount_fen": amount_fen,
        "trade_no": transaction_id,
    }

    # ── 5. 旁路发射事件 ──────────────────────────────────────────────────────────
    asyncio.create_task(
        emit_event(
            event_type=PaymentEventType.CONFIRMED,
            tenant_id=tenant_id_str,
            stream_id=str(order_uuid),
            payload={
                "order_no": order_snapshot["order_no"],
                "amount_fen": amount_fen,
                "payment_records": [payment_record],
                "channel": method,
                "transaction_id": transaction_id,
            },
            store_id=str(order_snapshot["store_id"]) if order_snapshot.get("store_id") else None,
            source_service="tx-trade",
            metadata={"trigger": f"{method}.notify"},
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
                    "payment_methods": [method],
                    "customer_id": str(order.customer_id) if order.customer_id else None,
                    "table_number": order.table_number,
                    "change_fen": 0,
                },
                store_id=str(order_snapshot["store_id"]) if order_snapshot.get("store_id") else None,
                source_service="tx-trade",
                metadata={"trigger": f"{method}.notify"},
            )
        )

    return {"duplicate": False}
