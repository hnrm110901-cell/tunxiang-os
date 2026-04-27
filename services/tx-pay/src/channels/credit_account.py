"""企业挂账支付渠道

通过 HTTP 调用 tx-finance 信用协议接口完成挂账。
挂账不产生实际资金流动，而是记录应收账款。

流程：
  1. tx-pay 调用 tx-finance POST /api/v1/credit/agreements/{id}/charge
  2. tx-finance 校验额度 → 记录挂账消费 → 返回结果
  3. 还款/核销走 tx-finance 独立流程
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

_TX_FINANCE_BASE = "http://localhost:8007"


class CreditAccountChannel(BasePaymentChannel):
    """企业挂账支付渠道"""

    channel_name = "credit_account"
    supported_methods = [PayMethod.CREDIT_ACCOUNT]
    supported_trade_types = [TradeType.B2C]

    def __init__(self, http_client: object = None) -> None:
        self._http = http_client

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"TAB{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        agreement_id = request.metadata.get("agreement_id")
        if not agreement_id:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.FAILED,
                method=PayMethod.CREDIT_ACCOUNT,
                amount_fen=request.amount_fen,
                error_code="MISSING_AGREEMENT",
                error_msg="挂账支付需要 agreement_id",
            )

        if self._http is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.CREDIT_ACCOUNT,
                amount_fen=request.amount_fen,
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "agreement_id": agreement_id},
            )

        resp = await self._http.post(
            f"{_TX_FINANCE_BASE}/api/v1/credit/agreements/{agreement_id}/charge",
            json={
                "order_id": request.order_id,
                "store_id": request.store_id,
                "charged_amount_fen": request.amount_fen,
            },
            headers={"X-Tenant-ID": request.tenant_id},
        )

        if resp.status_code == 200:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.CREDIT_ACCOUNT,
                amount_fen=request.amount_fen,
                paid_at=datetime.now(timezone.utc),
                channel_data=resp.json().get("data", {}),
            )

        error = resp.json().get("error", {})
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.FAILED,
            method=PayMethod.CREDIT_ACCOUNT,
            amount_fen=request.amount_fen,
            error_code=error.get("code", "CHARGE_FAILED"),
            error_msg=error.get("message", "挂账消费失败"),
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.SUCCESS,
            method=PayMethod.CREDIT_ACCOUNT,
            amount_fen=0,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFTAB{uuid.uuid4().hex[:10].upper()}"
        # 挂账退款 = 冲减应收账款，暂为 Mock
        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="success",
            amount_fen=refund_amount_fen,
            refunded_at=datetime.now(timezone.utc),
        )
