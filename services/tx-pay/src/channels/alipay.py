"""支付宝渠道 — 预留骨架

当前为 Mock 实现。正式对接时替换为支付宝 V3 SDK 调用。
接口与 BasePaymentChannel 完全兼容，切换无感。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from .base import (
    BasePaymentChannel,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    RefundResult,
    TradeType,
)

logger = structlog.get_logger(__name__)


class AlipayChannel(BasePaymentChannel):
    """支付宝渠道（Mock 骨架）"""

    channel_name = "alipay_direct"
    supported_methods = [PayMethod.ALIPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B, TradeType.JSAPI, TradeType.H5]

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
