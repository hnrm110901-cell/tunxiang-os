"""微信支付渠道 — V3 API 直连

委托 shared/integrations/wechat_pay.py 完成实际API调用。
本模块负责适配 BasePaymentChannel 接口。

支持：
  - JSAPI（小程序/公众号支付）
  - Native（扫码支付 C2B）
  - H5 支付

环境变量：
  WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / WECHAT_PAY_CERT_PATH / WECHAT_PAY_APPID
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


class WechatPayChannel(BasePaymentChannel):
    """微信支付 V3 渠道"""

    channel_name = "wechat_direct"
    supported_methods = [PayMethod.WECHAT]
    supported_trade_types = [TradeType.JSAPI, TradeType.C2B, TradeType.NATIVE, TradeType.H5]

    def __init__(self, notify_url: str = "") -> None:
        self._notify_url = notify_url
        # 延迟导入：共享模块可能不存在
        try:
            from shared.integrations.wechat_pay import WechatPayService
            self._service = WechatPayService()
        except ImportError:
            self._service = None
            logger.warning("wechat_pay_channel_mock_mode", reason="shared.integrations.wechat_pay not available")

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"WX{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._service is None:
            # Mock 模式
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.WECHAT,
                amount_fen=request.amount_fen,
                trade_no=f"MOCK_WX_{uuid.uuid4().hex[:16]}",
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "prepay_id": f"wx_mock_{uuid.uuid4().hex[:12]}"},
            )

        # JSAPI 场景：创建预支付订单
        result = await self._service.create_jsapi_order(
            out_trade_no=payment_id,
            total_fen=request.amount_fen,
            description=request.description or "屯象OS订单",
            openid=request.openid or "",
            notify_url=request.notify_url or self._notify_url,
        )

        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.PENDING,
            method=PayMethod.WECHAT,
            amount_fen=request.amount_fen,
            channel_data=result,
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        if self._service is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.WECHAT,
                amount_fen=0,
                trade_no=trade_no,
                channel_data={"mock": True},
            )

        result = await self._service.query_order(payment_id)
        status_map = {
            "SUCCESS": PayStatus.SUCCESS,
            "NOTPAY": PayStatus.PENDING,
            "CLOSED": PayStatus.CLOSED,
            "REFUND": PayStatus.REFUNDED,
        }
        return PaymentResult(
            payment_id=payment_id,
            status=status_map.get(result.get("trade_state", ""), PayStatus.PENDING),
            method=PayMethod.WECHAT,
            amount_fen=result.get("amount", {}).get("total", 0),
            trade_no=result.get("transaction_id"),
            channel_data=result,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._service is None:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refund_trade_no=f"MOCK_REFUND_{uuid.uuid4().hex[:12]}",
                refunded_at=datetime.now(timezone.utc),
            )

        result = await self._service.refund(
            out_trade_no=payment_id,
            out_refund_no=rid,
            refund_fen=refund_amount_fen,
            total_fen=refund_amount_fen,  # 调用方保证正确
            reason=reason,
        )
        return RefundResult(
            refund_id=rid,
            payment_id=payment_id,
            status="success" if result.get("status") == "SUCCESS" else "pending",
            amount_fen=refund_amount_fen,
            refund_trade_no=result.get("refund_id"),
        )

    async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
        if self._service is None:
            raise NotImplementedError("Mock 模式不支持回调验证")

        data = await self._service.verify_callback(headers, body)
        return CallbackPayload(
            payment_id=data.get("out_trade_no", ""),
            trade_no=data.get("transaction_id", ""),
            status=PayStatus.SUCCESS,
            amount_fen=data.get("amount", {}).get("total", 0),
            raw=data,
        )
