"""支付直连 — 微信/支付宝/银联 mock SDK + 风控 + 并发支付

所有支付 API 为 mock 实现，接口与微信/支付宝 SDK 兼容。
"""
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

# ─── 内存存储（mock） ───

_payments: dict[str, dict] = {}  # key: payment_id
_risk_records: dict[str, dict] = {}  # key: order_id


class DirectPaymentStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CLOSED = "closed"
    REFUNDED = "refunded"
    PARTIAL_REFUND = "partial_refund"


class PaymentChannel:
    WECHAT = "wechat"
    ALIPAY = "alipay"
    UNIONPAY = "unionpay"


def _gen_trade_no(prefix: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{prefix}{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"


async def create_wechat_payment(
    order_id: str,
    amount_fen: int,
    tenant_id: str,
    db=None,
    *,
    openid: Optional[str] = None,
    trade_type: str = "JSAPI",
    description: str = "",
) -> dict:
    """微信支付下单（mock）

    返回与微信支付 JSAPI 兼容的响应结构:
    {
        "prepay_id": str,
        "payment_id": str,
        "appId": str,
        "timeStamp": str,
        "nonceStr": str,
        "package": str,
        "signType": str,
        "paySign": str
    }
    """
    if amount_fen <= 0:
        raise ValueError("amount_fen must be positive")

    payment_id = str(uuid.uuid4())
    prepay_id = f"wx{uuid.uuid4().hex[:28]}"
    trade_no = _gen_trade_no("WX")
    nonce = uuid.uuid4().hex[:16]
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))

    payment = {
        "id": payment_id,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "channel": PaymentChannel.WECHAT,
        "amount_fen": amount_fen,
        "trade_no": trade_no,
        "prepay_id": prepay_id,
        "status": DirectPaymentStatus.SUCCESS,  # mock: 直接成功
        "openid": openid,
        "trade_type": trade_type,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
    _payments[payment_id] = payment

    logger.info(
        "wechat_payment_created",
        payment_id=payment_id,
        order_id=order_id,
        amount_fen=amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "payment_id": payment_id,
        "prepay_id": prepay_id,
        "trade_no": trade_no,
        "appId": "wx_mock_app_id",
        "timeStamp": timestamp,
        "nonceStr": nonce,
        "package": f"prepay_id={prepay_id}",
        "signType": "RSA",
        "paySign": f"mock_sign_{nonce}",
    }


async def create_alipay_payment(
    order_id: str,
    amount_fen: int,
    tenant_id: str,
    db=None,
    *,
    buyer_id: Optional[str] = None,
    subject: str = "",
) -> dict:
    """支付宝支付下单（mock）

    返回与支付宝 SDK 兼容的响应结构:
    {
        "payment_id": str,
        "trade_no": str,
        "out_trade_no": str,
        "total_amount": str,    # 元，两位小数
        "trade_status": str
    }
    """
    if amount_fen <= 0:
        raise ValueError("amount_fen must be positive")

    payment_id = str(uuid.uuid4())
    trade_no = _gen_trade_no("ALI")
    out_trade_no = _gen_trade_no("TX")

    payment = {
        "id": payment_id,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "channel": PaymentChannel.ALIPAY,
        "amount_fen": amount_fen,
        "trade_no": trade_no,
        "out_trade_no": out_trade_no,
        "status": DirectPaymentStatus.SUCCESS,
        "buyer_id": buyer_id,
        "subject": subject,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
    _payments[payment_id] = payment

    logger.info(
        "alipay_payment_created",
        payment_id=payment_id,
        order_id=order_id,
        amount_fen=amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "payment_id": payment_id,
        "trade_no": trade_no,
        "out_trade_no": out_trade_no,
        "total_amount": f"{amount_fen / 100:.2f}",
        "trade_status": "TRADE_SUCCESS",
    }


async def create_unionpay_payment(
    order_id: str,
    amount_fen: int,
    tenant_id: str,
    db=None,
    *,
    card_no_masked: Optional[str] = None,
) -> dict:
    """银联支付下单（mock）

    返回与银联 SDK 兼容的响应结构
    """
    if amount_fen <= 0:
        raise ValueError("amount_fen must be positive")

    payment_id = str(uuid.uuid4())
    trade_no = _gen_trade_no("UP")
    query_id = _gen_trade_no("QID")

    payment = {
        "id": payment_id,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "channel": PaymentChannel.UNIONPAY,
        "amount_fen": amount_fen,
        "trade_no": trade_no,
        "query_id": query_id,
        "status": DirectPaymentStatus.SUCCESS,
        "card_no_masked": card_no_masked,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
    _payments[payment_id] = payment

    logger.info(
        "unionpay_payment_created",
        payment_id=payment_id,
        order_id=order_id,
        amount_fen=amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "payment_id": payment_id,
        "trade_no": trade_no,
        "queryId": query_id,
        "respCode": "00",
        "respMsg": "success",
        "txnAmt": str(amount_fen),
    }


async def query_payment_status(
    payment_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """查询支付状态"""
    payment = _payments.get(payment_id)
    if not payment:
        raise ValueError(f"Payment not found: {payment_id}")
    if payment["tenant_id"] != tenant_id:
        raise PermissionError("Payment does not belong to this tenant")

    logger.info(
        "payment_status_queried",
        payment_id=payment_id,
        tenant_id=tenant_id,
        status=payment["status"],
    )
    return {
        "payment_id": payment_id,
        "order_id": payment["order_id"],
        "channel": payment["channel"],
        "amount_fen": payment["amount_fen"],
        "status": payment["status"],
        "trade_no": payment["trade_no"],
        "paid_at": payment.get("paid_at"),
    }


async def process_refund(
    payment_id: str,
    amount_fen: int,
    reason: str,
    tenant_id: str,
    db=None,
) -> dict:
    """退款（mock）"""
    payment = _payments.get(payment_id)
    if not payment:
        raise ValueError(f"Payment not found: {payment_id}")
    if payment["tenant_id"] != tenant_id:
        raise PermissionError("Payment does not belong to this tenant")
    if payment["status"] not in (DirectPaymentStatus.SUCCESS, DirectPaymentStatus.PARTIAL_REFUND):
        raise ValueError(f"Payment status {payment['status']} cannot be refunded")
    if amount_fen <= 0:
        raise ValueError("Refund amount must be positive")
    if amount_fen > payment["amount_fen"]:
        raise ValueError("Refund amount exceeds payment amount")

    refund_id = str(uuid.uuid4())
    refund_no = _gen_trade_no("REF")

    if amount_fen == payment["amount_fen"]:
        payment["status"] = DirectPaymentStatus.REFUNDED
    else:
        payment["status"] = DirectPaymentStatus.PARTIAL_REFUND

    logger.info(
        "payment_refund_processed",
        payment_id=payment_id,
        refund_id=refund_id,
        amount_fen=amount_fen,
        reason=reason,
        tenant_id=tenant_id,
    )
    return {
        "refund_id": refund_id,
        "refund_no": refund_no,
        "payment_id": payment_id,
        "amount_fen": amount_fen,
        "status": "refund_success",
        "channel": payment["channel"],
    }


async def handle_concurrent_payment(
    order_id: str,
    payments: list[dict],
    tenant_id: str,
    db=None,
) -> dict:
    """并发支付 — 一笔订单同时使用多种支付方式

    payments 示例:
    [
        {"channel": "wechat", "amount_fen": 5000},
        {"channel": "alipay", "amount_fen": 3000},
        {"channel": "unionpay", "amount_fen": 2000}
    ]
    """
    total_fen = sum(p["amount_fen"] for p in payments)
    results: list[dict] = []
    failed: list[dict] = []

    channel_handlers = {
        PaymentChannel.WECHAT: create_wechat_payment,
        PaymentChannel.ALIPAY: create_alipay_payment,
        PaymentChannel.UNIONPAY: create_unionpay_payment,
    }

    tasks = []
    for p in payments:
        channel = p["channel"]
        handler = channel_handlers.get(channel)
        if not handler:
            failed.append({"channel": channel, "error": f"Unsupported channel: {channel}"})
            continue
        tasks.append((channel, handler(order_id, p["amount_fen"], tenant_id, db)))

    for channel, coro in tasks:
        try:
            result = await coro
            results.append(result)
        except (ValueError, PermissionError) as e:
            failed.append({"channel": channel, "error": str(e)})

    all_success = len(failed) == 0 and len(results) == len(payments)

    logger.info(
        "concurrent_payment_handled",
        order_id=order_id,
        tenant_id=tenant_id,
        total_fen=total_fen,
        success_count=len(results),
        failed_count=len(failed),
    )
    return {
        "order_id": order_id,
        "total_fen": total_fen,
        "all_success": all_success,
        "payments": results,
        "failed": failed,
    }


async def get_payment_risk_check(
    order_id: str,
    tenant_id: str,
    db=None,
    *,
    amount_fen: int = 0,
    payment_count_today: int = 0,
) -> dict:
    """风控检查（mock）

    检查规则:
    1. 单笔金额超过 100000 分 (1000元) 需人工确认
    2. 当日支付次数超过 50 次预警
    3. 金额为 0 拒绝
    """
    risk_level = "low"
    risk_flags: list[str] = []
    allow = True

    if amount_fen == 0:
        risk_level = "rejected"
        risk_flags.append("zero_amount")
        allow = False

    if amount_fen > 100000:
        risk_level = "high"
        risk_flags.append("large_amount")

    if payment_count_today > 50:
        if risk_level != "high":
            risk_level = "medium"
        risk_flags.append("high_frequency")

    result = {
        "order_id": order_id,
        "tenant_id": tenant_id,
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "allow": allow,
        "requires_confirmation": risk_level == "high",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    _risk_records[order_id] = result

    logger.info(
        "payment_risk_checked",
        order_id=order_id,
        tenant_id=tenant_id,
        risk_level=risk_level,
        allow=allow,
    )
    return result
