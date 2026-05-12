"""支付宝渠道 — 预留骨架

当前为 Mock 实现。正式对接时替换为支付宝 V3 SDK 调用。
接口与 BasePaymentChannel 完全兼容，切换无感。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import structlog

from .base import (
    BasePaymentChannel,
    CallbackPayload,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    RefundResult,
    TradeType,
)

logger = structlog.get_logger(__name__)


# 支付宝 trade_status → 内部 PayStatus 映射
_TRADE_STATUS_MAP = {
    "TRADE_SUCCESS": PayStatus.SUCCESS,
    "TRADE_FINISHED": PayStatus.SUCCESS,
    "WAIT_BUYER_PAY": PayStatus.PENDING,
    "TRADE_CLOSED": PayStatus.CLOSED,
}


class AlipayChannel(BasePaymentChannel):
    """支付宝渠道（pay/query/refund Mock 骨架；verify_callback 已委托真实 SDK）"""

    channel_name = "alipay_direct"
    supported_methods = [PayMethod.ALIPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B, TradeType.JSAPI, TradeType.H5]

    def __init__(self) -> None:
        try:
            from shared.integrations.alipay_sdk import AlipayService

            self._service = AlipayService()
        except ImportError:
            self._service = None
            logger.warning(
                "alipay_channel_mock_mode",
                reason="shared.integrations.alipay_sdk not available",
            )

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"ALI{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        logger.info("alipay_mock_pay", payment_id=payment_id, amount_fen=request.amount_fen)
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.SUCCESS,
            method=PayMethod.ALIPAY,
            amount_fen=request.amount_fen,
            trade_no=f"MOCK_ALI_{uuid.uuid4().hex[:16]}",
            paid_at=datetime.now(timezone.utc),
            channel_data={"mock": True},
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.SUCCESS,
            method=PayMethod.ALIPAY,
            amount_fen=0,
            trade_no=trade_no,
            channel_data={"mock": True},
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFALI{uuid.uuid4().hex[:10].upper()}"
        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="success",
            amount_fen=refund_amount_fen,
            refund_trade_no=f"MOCK_REFALI_{uuid.uuid4().hex[:12]}",
            refunded_at=datetime.now(timezone.utc),
        )

    async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
        """支付宝异步通知验签 + 业务字段提取。

        注意：支付宝 total_amount 单位是**元**（小数字符串如 "88.00"），
        必须 *100 转分（int）落入 CallbackPayload.amount_fen。
        """
        if self._service is None:
            raise NotImplementedError("AlipayService 未初始化，无法验签")

        params = await self._service.verify_callback(headers, body)

        trade_status = params.get("trade_status", "")
        status = _TRADE_STATUS_MAP.get(trade_status, PayStatus.PENDING)
        if trade_status and trade_status not in _TRADE_STATUS_MAP:
            # P1-3: 未知状态降级 PENDING 是保守安全的（不会误触发资金确认），
            # 但需要观测发现意外状态值用于扩展映射。
            logger.warning(
                "alipay_unknown_trade_status",
                trade_status=trade_status,
                out_trade_no=params.get("out_trade_no"),
            )

        # P1-2: 元 → 分用 Decimal 避免浮点精度问题（如 2.675 * 100 = 267.49999...）
        # 支付宝 total_amount 是元单位字符串（如 "88.00"），其他渠道全是分。
        total_yuan = params.get("total_amount", "0")
        try:
            amount_fen = int(Decimal(total_yuan) * 100)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"支付宝回调 total_amount 非法：{total_yuan}") from exc

        return CallbackPayload(
            payment_id=params.get("out_trade_no", ""),
            trade_no=params.get("trade_no", ""),
            status=status,
            amount_fen=amount_fen,
            raw=params,
        )
