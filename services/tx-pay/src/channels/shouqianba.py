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
    CallbackPayload,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    RefundResult,
    TradeType,
)

logger = structlog.get_logger(__name__)


# 收钱吧 order_status → 内部 PayStatus 映射
_ORDER_STATUS_MAP = {
    "PAID": PayStatus.SUCCESS,
    "PAY_SUCCESS": PayStatus.SUCCESS,
    "IN_PROGRESS": PayStatus.PENDING,
    "CREATED": PayStatus.PENDING,
    "PAY_CANCELED": PayStatus.CLOSED,
    "CANCELED": PayStatus.CLOSED,
    "REFUNDED": PayStatus.REFUNDED,
    "PARTIAL_REFUNDED": PayStatus.PARTIAL_REFUND,
}


class ShouqianbaChannel(BasePaymentChannel):
    """收钱吧聚合支付渠道"""

    # E2: 必须与 callback_routes.py `registry.get("shouqianba_direct")` 对齐，
    # 否则 callback 永远走 None → 500 不可达。
    channel_name = "shouqianba_direct"
    supported_methods = [PayMethod.WECHAT, PayMethod.ALIPAY, PayMethod.UNIONPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B]

    def __init__(self, client: object = None) -> None:
        self._client = client
        # 委托真实 SDK 做 verify_callback（pay/query/refund 仍走 client mock 路径）
        try:
            from shared.integrations.shouqianba_sdk import ShouqianbaService

            self._service = ShouqianbaService()
        except ImportError:
            self._service = None
            logger.warning(
                "shouqianba_channel_mock_mode",
                reason="shared.integrations.shouqianba_sdk not available",
            )

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

    async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
        """收钱吧终端通知验签 + 业务字段提取。

        签名机制：Authorization: `<sn> <sign>`，sign = MD5(body + terminal_key)。
        body 为 JSON，total_amount 单位为**分**（无需元转分，与其他渠道一致）。
        未知 order_status 降级 PENDING（保守安全，不会误触发资金确认）。
        """
        if self._service is None:
            raise NotImplementedError("ShouqianbaService 未初始化，无法验签")

        data = await self._service.verify_callback(headers, body)

        order_status = data.get("order_status", "")
        status = _ORDER_STATUS_MAP.get(order_status, PayStatus.PENDING)
        if order_status and order_status not in _ORDER_STATUS_MAP:
            logger.warning(
                "shouqianba_unknown_order_status",
                order_status=order_status,
                client_sn=data.get("client_sn"),
            )

        # 收钱吧 total_amount 已是分字符串
        try:
            amount_fen = int(data.get("total_amount", "0"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"收钱吧回调 total_amount 非法：{data.get('total_amount')!r}"
            ) from exc

        return CallbackPayload(
            payment_id=data.get("client_sn", ""),
            trade_no=data.get("sn", ""),
            status=status,
            amount_fen=amount_fen,
            raw=data,
        )
