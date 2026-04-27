"""会员储值余额支付渠道

通过 HTTP 调用 tx-member 服务完成储值扣减。
tx-pay 不直接操作 stored_value_cards 表，保持服务边界清晰。

流程：
  1. tx-pay 调用 tx-member POST /api/v1/member/stored-value/deduct
  2. tx-member 校验余额 → 扣减 → 返回结果
  3. 退款时 tx-pay 调用 tx-member POST /api/v1/member/stored-value/refund
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

# tx-member 服务地址（通过环境变量或服务发现获取）
_TX_MEMBER_BASE = "http://localhost:8003"


class StoredValueChannel(BasePaymentChannel):
    """会员储值余额支付渠道"""

    channel_name = "stored_value"
    supported_methods = [PayMethod.MEMBER_BALANCE]
    supported_trade_types = [TradeType.B2C]

    def __init__(self, http_client: object = None) -> None:
        """
        Args:
            http_client: httpx.AsyncClient 实例（None 时 Mock）
        """
        self._http = http_client

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"SV{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._http is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.MEMBER_BALANCE,
                amount_fen=request.amount_fen,
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "member_id": request.metadata.get("member_id")},
            )

        member_id = request.metadata.get("member_id")
        if not member_id:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.FAILED,
                method=PayMethod.MEMBER_BALANCE,
                amount_fen=request.amount_fen,
                error_code="MISSING_MEMBER_ID",
                error_msg="储值支付需要 member_id",
            )

        resp = await self._http.post(
            f"{_TX_MEMBER_BASE}/api/v1/member/stored-value/deduct",
            json={
                "member_id": member_id,
                "amount_fen": request.amount_fen,
                "order_id": request.order_id,
                "idempotency_key": request.idempotency_key,
            },
            headers={"X-Tenant-ID": request.tenant_id},
        )

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.MEMBER_BALANCE,
                amount_fen=request.amount_fen,
                paid_at=datetime.now(timezone.utc),
                channel_data={"remaining_balance_fen": data.get("remaining_balance_fen")},
            )

        error = resp.json().get("error", {})
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.FAILED,
            method=PayMethod.MEMBER_BALANCE,
            amount_fen=request.amount_fen,
            error_code=error.get("code", "DEDUCT_FAILED"),
            error_msg=error.get("message", "储值扣减失败"),
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.SUCCESS,
            method=PayMethod.MEMBER_BALANCE,
            amount_fen=0,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFSV{uuid.uuid4().hex[:10].upper()}"

        if self._http is None:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refunded_at=datetime.now(timezone.utc),
            )

        # 调用 tx-member 退还余额
        resp = await self._http.post(
            f"{_TX_MEMBER_BASE}/api/v1/member/stored-value/refund",
            json={
                "payment_id": payment_id,
                "refund_amount_fen": refund_amount_fen,
                "reason": reason,
                "refund_id": rid,
            },
        )

        if resp.status_code == 200:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refunded_at=datetime.now(timezone.utc),
            )

        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="failed",
            amount_fen=refund_amount_fen,
            error_msg="储值退款失败",
        )
