"""拉卡拉聚合支付渠道

委托 services/tx-trade/src/services/lakala_client.py 完成实际调用。
迁移完成后 lakala_client 将移入 tx-pay。

支持：
  - B扫C（Micropay 条码支付）
  - C扫B（JSAPI / 动态二维码）
  - 退款 / 查询 / 关闭
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


class LakalaChannel(BasePaymentChannel):
    """拉卡拉聚合支付渠道"""

    channel_name = "lakala"
    supported_methods = [PayMethod.WECHAT, PayMethod.ALIPAY, PayMethod.UNIONPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B, TradeType.JSAPI]

    def __init__(self, client: object = None) -> None:
        """
        Args:
            client: LakalaClient 实例（None 时为 Mock 模式）
        """
        self._client = client

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"LKL{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._client is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=request.method,
                amount_fen=request.amount_fen,
                trade_no=f"MOCK_LKL_{uuid.uuid4().hex[:16]}",
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "provider": "lakala"},
            )

        # B扫C 场景
        if request.trade_type == TradeType.B2C and request.auth_code:
            result = await self._client.micropay(
                out_trade_no=payment_id,
                auth_code=request.auth_code,
                total_fee=request.amount_fen,
                body=request.description or "屯象OS订单",
            )
        else:
            # C扫B / JSAPI
            result = await self._client.create_qr(
                out_trade_no=payment_id,
                total_fee=request.amount_fen,
                body=request.description or "屯象OS订单",
            )

        status = PayStatus.SUCCESS if result.get("trade_state") == "SUCCESS" else PayStatus.PENDING
        return PaymentResult(
            payment_id=payment_id,
            status=status,
            method=request.method,
            amount_fen=request.amount_fen,
            trade_no=result.get("channel_trade_no"),
            paid_at=datetime.now(timezone.utc) if status == PayStatus.SUCCESS else None,
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
        status_map = {"SUCCESS": PayStatus.SUCCESS, "PAYING": PayStatus.PENDING, "CLOSED": PayStatus.CLOSED}
        return PaymentResult(
            payment_id=payment_id,
            status=status_map.get(result.get("trade_state", ""), PayStatus.PENDING),
            method=PayMethod.WECHAT,
            amount_fen=result.get("total_fee", 0),
            trade_no=result.get("channel_trade_no"),
            channel_data=result,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFLKL{uuid.uuid4().hex[:10].upper()}"

        if self._client is None:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refund_trade_no=f"MOCK_REFLKL_{uuid.uuid4().hex[:12]}",
                refunded_at=datetime.now(timezone.utc),
            )

        result = await self._client.refund(
            out_trade_no=payment_id,
            refund_fee=refund_amount_fen,
            out_refund_no=rid,
        )
        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="success" if result.get("result_code") == "SUCCESS" else "failed",
            amount_fen=refund_amount_fen,
            refund_trade_no=result.get("refund_trade_no"),
        )
