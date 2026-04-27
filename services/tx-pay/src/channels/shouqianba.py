"""收钱吧聚合支付渠道

委托 services/tx-trade/src/services/shouqianba_client.py 完成实际调用。
迁移完成后 shouqianba_client 将移入 tx-pay。

支持：
  - B扫C（pay 条码支付）
  - C扫B（precreate 生成二维码）
  - 退款 / 查询 / 撤单
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


class ShouqianbaChannel(BasePaymentChannel):
    """收钱吧聚合支付渠道"""

    channel_name = "shouqianba"
    supported_methods = [PayMethod.WECHAT, PayMethod.ALIPAY, PayMethod.UNIONPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B]

    def __init__(self, client: object = None) -> None:
        self._client = client

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"SQB{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._client is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=request.method,
                amount_fen=request.amount_fen,
                trade_no=f"MOCK_SQB_{uuid.uuid4().hex[:16]}",
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "provider": "shouqianba"},
            )

        if request.trade_type == TradeType.B2C and request.auth_code:
            result = await self._client.pay(
                out_trade_no=payment_id,
                auth_code=request.auth_code,
                total_amount=str(request.amount_fen),
                subject=request.description or "屯象OS订单",
            )
        else:
            result = await self._client.precreate(
                out_trade_no=payment_id,
                total_amount=str(request.amount_fen),
                subject=request.description or "屯象OS订单",
            )

        sqb_status = result.get("order_status", "")
        status_map = {
            "PAID": PayStatus.SUCCESS,
            "PAY_SUCCESS": PayStatus.SUCCESS,
            "IN_PROGRESS": PayStatus.PENDING,
            "PAY_CANCELED": PayStatus.CLOSED,
        }
        return PaymentResult(
            payment_id=payment_id,
            status=status_map.get(sqb_status, PayStatus.PENDING),
            method=request.method,
            amount_fen=request.amount_fen,
            trade_no=result.get("sn"),
            paid_at=datetime.now(timezone.utc) if sqb_status in ("PAID", "PAY_SUCCESS") else None,
            channel_data=result,
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        if self._client is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.WECHAT,
                amount_fen=0,
                trade_no=trade_no,
                channel_data={"mock": True},
            )

        result = await self._client.query(out_trade_no=payment_id)
        sqb_status = result.get("order_status", "")
        status_map = {
            "PAID": PayStatus.SUCCESS,
            "PAY_SUCCESS": PayStatus.SUCCESS,
            "IN_PROGRESS": PayStatus.PENDING,
            "PAY_CANCELED": PayStatus.CLOSED,
            "REFUNDED": PayStatus.REFUNDED,
            "PARTIAL_REFUNDED": PayStatus.PARTIAL_REFUND,
        }
        return PaymentResult(
            payment_id=payment_id,
            status=status_map.get(sqb_status, PayStatus.PENDING),
            method=PayMethod.WECHAT,
            amount_fen=int(result.get("total_amount", "0")),
            trade_no=result.get("sn"),
            channel_data=result,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFSQB{uuid.uuid4().hex[:10].upper()}"

        if self._client is None:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refund_trade_no=f"MOCK_REFSQB_{uuid.uuid4().hex[:12]}",
                refunded_at=datetime.now(timezone.utc),
            )

        result = await self._client.refund(
            out_trade_no=payment_id,
            refund_amount=str(refund_amount_fen),
            refund_request_no=rid,
        )
        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="success" if result.get("result_code") == "SUCCESS" else "pending",
            amount_fen=refund_amount_fen,
            refund_trade_no=result.get("sn"),
        )
