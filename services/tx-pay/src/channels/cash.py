"""现金支付渠道

现金支付不涉及第三方 API 调用，仅记录支付事实。
由收银员在 POS 端确认收款后调用。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from .base import (
    BasePaymentChannel,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    RefundResult,
    TradeType,
)


class CashChannel(BasePaymentChannel):
    """现金支付渠道"""

    channel_name = "cash"
    supported_methods = [PayMethod.CASH]
    supported_trade_types = [TradeType.B2C]

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            payment_id=f"CASH{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}",
            status=PayStatus.SUCCESS,
            method=PayMethod.CASH,
            amount_fen=request.amount_fen,
            paid_at=datetime.now(timezone.utc),
            channel_data={"change_fen": request.metadata.get("tendered_fen", 0) - request.amount_fen},
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.SUCCESS,
            method=PayMethod.CASH,
            amount_fen=0,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        return RefundResult(
            refund_id=refund_id or f"REFCASH{uuid.uuid4().hex[:10].upper()}",
            payment_id=payment_id,
            status="success",
            amount_fen=refund_amount_fen,
            refunded_at=datetime.now(timezone.utc),
        )
