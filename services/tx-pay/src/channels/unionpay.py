"""云闪付（银联 UnionPay）支付渠道 — skeleton 占位

PR4 决策 B：spec NO-GO 全套实现（document-specialist 评估）。
本 channel 仅做 ChannelRegistry 注册 + Mock 模式 + verify_callback NotImplementedError，
等创始人提供以下凭据后另起 PR 落地真验签：
  - 银联颁发商户 .pfx（含 X.509 cert + 私钥）+ middle/root .cer 证书链
  - 测试环境 merId + 凭据
  - 餐饮场景 product line 合约确认（UPOP 网关 / B扫C / C扫B / 云闪付 App / 控件）

不实现 verify_callback 真验签的理由（详见 backlog issue）：
  1. UnionPay 公开文档分裂：UPOP 用 SHA-256+RSA 字母序排序；OpenAPI 用 SHA-256+固定序；
     云闪付控件用 SHA-1+RSA — 三套不同算法，需合约确认走哪条
  2. certId = X.509 cert.getSerialNumber()，回调验签需要本地证书池（PKIX 三证链：
     root → middle → leaf），仅有 leaf 公钥不能完成 PKIX 验证
  3. 无商户证书 + 无测试环境 → Mock 与生产行为不等价 → 伪造 callback 无法检测
     → 违反 §17 Tier1 零容忍
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


class UnionPayChannel(BasePaymentChannel):
    """云闪付（银联）支付渠道 — skeleton（凭据前置）"""

    channel_name = "unionpay"
    supported_methods = [PayMethod.UNIONPAY]
    supported_trade_types = [TradeType.B2C, TradeType.C2B, TradeType.JSAPI]

    def __init__(self, client: object = None) -> None:
        """
        Args:
            client: UnionPayClient 实例（None 时为 Mock 模式）。
                    凭据 PR 落地前一律 None，此参数预留接口稳定性。
        """
        self._client = client

    async def pay(self, request: PaymentRequest) -> PaymentResult:
        payment_id = f"UP{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        if self._client is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.UNIONPAY,
                amount_fen=request.amount_fen,
                trade_no=f"MOCK_UP_{uuid.uuid4().hex[:16]}",
                paid_at=datetime.now(timezone.utc),
                channel_data={"mock": True, "provider": "unionpay"},
            )

        raise NotImplementedError(
            "UnionPay pay() 真实模式未实现：等待商户证书链（.pfx + middle/root .cer）"
            "+ 测试环境 merId 凭据 + 餐饮场景 product line 合约确认"
        )

    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        if self._client is None:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus.SUCCESS,
                method=PayMethod.UNIONPAY,
                amount_fen=0,
                trade_no=trade_no or f"MOCK_UP_{uuid.uuid4().hex[:16]}",
                channel_data={"mock": True, "provider": "unionpay"},
            )

        raise NotImplementedError(
            "UnionPay query() 真实模式未实现：等待商户证书链凭据"
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        rid = refund_id or f"REFUP{uuid.uuid4().hex[:10].upper()}"

        if self._client is None:
            return RefundResult(
                refund_id=rid,
                payment_id=payment_id,
                status="success",
                amount_fen=refund_amount_fen,
                refund_trade_no=f"MOCK_REFUP_{uuid.uuid4().hex[:12]}",
                refunded_at=datetime.now(timezone.utc),
            )

        raise NotImplementedError(
            "UnionPay refund() 真实模式未实现：等待商户证书链凭据"
        )

    async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
        """异步回调验签 — 显式 NotImplementedError 占位

        生产环境 callback 必须立即抛错（不能 fallback "假成功"），避免：
          - 静默接受伪造 callback → 误判为已收款 → 财务穿透
          - 错误 fallback 到 success → 库存扣减 → 资金损失

        实施前置条件（开 backlog issue 跟进）：
          1. 银联颁发商户 .pfx（含私钥 + leaf cert）
          2. 银联 middle/root .cer 证书链（PKIX 校验必须）
          3. 测试环境 merId + 凭据
          4. 餐饮场景 product line 合约确认（决定签名算法 SHA-1 vs SHA-256
             以及参数排序规则字母序 vs 固定序）
        """
        raise NotImplementedError(
            "UnionPay 回调验签需要商户证书链（.pfx + middle/root .cer 三证 PKIX），"
            "等待创始人提供商户凭据 + 测试环境 merId 后实施。"
            "本 skeleton 仅占位防伪造 callback 静默通过。"
        )
