"""云闪付（银联）渠道 skeleton Tier 1 测试（餐厅场景 + audit-friendly 占位）

场景动机：
  PR4 决策 B（skeleton 占位）— 在 ChannelRegistry 注册 UnionPayChannel，但 verify_callback
  显式抛 NotImplementedError 标明"凭据前置"，避免：
    1. 凭据未到位时基于公开 PDF 自造验签实现，被 attacker 用伪造 callback 绕过
    2. /api/v1/pay/callback/unionpay 路由不存在时被探测为"隐藏未来路径"

涉及 Tier 1 路径：支付补偿 Saga 渠道注册（§17）— TDD 红绿双 commit。

UnionPay 凭据前置（spec NO-GO 理由，详见 document-specialist 评估）：
  - 公开文档分裂（UPOP / OpenAPI / 控件 三套体系签名规则不同 SHA-1 vs SHA-256）
  - certId / X.509 PKIX 三证链不可绕过（root → middle → leaf）
  - 餐饮场景 product line（UPOP 网关 / B扫C / C扫B / 云闪付 App）需创始人合约确认
  - 无商户 .pfx + 银联 middle/root .cer + 测试环境 merId → Mock 与生产不等价

backlog issue 待开：UnionPay 全套接入凭据前置（参考拉卡拉 backlog 同款模式）。
"""

from __future__ import annotations

import pytest

from services.tx_pay.src.channels.base import PayMethod, PayStatus, PaymentRequest, TradeType
from services.tx_pay.src.channels.registry import ChannelRegistry
from services.tx_pay.src.channels.unionpay import UnionPayChannel


class TestUnionPaySkeletonTier1:
    """云闪付 skeleton — registry 注册 + Mock pay + verify_callback NotImplementedError"""

    def test_channel_name_aligned_with_payment_service_registry(self) -> None:
        """场景：payment_service.py PAY_METHOD_PRIORITY 的 'unionpay' key 必须能 lookup 到
        registry.get('unionpay')，否则 routing engine 找不到 channel 直接 500。
        """
        channel = UnionPayChannel()
        assert channel.channel_name == "unionpay", (
            "channel_name 必须与 payment_service.py PAY_METHOD_PRIORITY key 一致"
        )

    def test_channel_registers_into_registry_without_error(self) -> None:
        """场景：tx-pay 启动时 main.py 调 registry.register(UnionPayChannel())，
        skeleton 必须能正常注册不抛错，否则整个服务启动失败。
        """
        registry = ChannelRegistry()
        registry.register(UnionPayChannel())
        assert registry.get("unionpay").channel_name == "unionpay"

    def test_channel_advertises_unionpay_method(self) -> None:
        """场景：routing engine 按 PayMethod.UNIONPAY 找 channel，
        UnionPayChannel 必须声明 supports UNIONPAY，否则 method dispatch 失败。
        """
        channel = UnionPayChannel()
        assert PayMethod.UNIONPAY in channel.supported_methods

    @pytest.mark.asyncio
    async def test_mock_mode_pay_returns_success(self) -> None:
        """场景：dev / demo 环境无凭据（client=None），收银员扫顾客云闪付付款码时，
        Mock 模式返回 SUCCESS（开发环境跑通流程），不抛 NotImplementedError 阻塞 demo。
        """
        channel = UnionPayChannel(client=None)
        request = PaymentRequest(
            tenant_id="test_tenant",
            store_id="test_store",
            order_id="test_order",
            amount_fen=8800,
            method=PayMethod.UNIONPAY,
            trade_type=TradeType.B2C,
            auth_code="62000000000000001234",
        )
        result = await channel.pay(request)
        assert result.status == PayStatus.SUCCESS
        assert result.amount_fen == 8800
        assert result.channel_data.get("mock") is True
        assert result.channel_data.get("provider") == "unionpay"

    @pytest.mark.asyncio
    async def test_verify_callback_raises_not_implemented_with_credential_message(
        self,
    ) -> None:
        """场景（核心 audit 反测）：生产环境若收到任何 callback POST，必须立即
        NotImplementedError + 明确 message"等待商户证书链凭据"，避免：
        - 静默接受伪造 callback → 误判为已收款 → 财务穿透
        - 错误 fallback 到"假成功" → 库存扣减 → 资金损失
        message 必须含"证书"或"凭据"字样让 reviewer 一眼看清是 deliberate 占位。
        """
        channel = UnionPayChannel(client=None)
        with pytest.raises(NotImplementedError) as exc_info:
            await channel.verify_callback(
                headers={"x-test": "fake"}, body=b'{"fake": "callback"}'
            )
        err_msg = str(exc_info.value)
        assert "证书" in err_msg or "凭据" in err_msg or "certificate" in err_msg.lower(), (
            f"NotImplementedError message 必须显式说明凭据前置原因，got: {err_msg!r}"
        )

    @pytest.mark.asyncio
    async def test_verify_callback_message_does_not_imply_success(self) -> None:
        """场景：NotImplementedError message 不能含"已收款 / success / paid"字样，
        防止 callback handler 误把 NotImplementedError 当 "通用 ok signal" 处理。
        """
        channel = UnionPayChannel(client=None)
        with pytest.raises(NotImplementedError) as exc_info:
            await channel.verify_callback(headers={}, body=b"")
        err_msg = str(exc_info.value).lower()
        for forbidden in ("success", "paid", "已收款", "ok"):
            assert forbidden not in err_msg, (
                f"NotImplementedError message 不能含模糊 success 语义 {forbidden!r}, "
                f"否则上层 except 路径可能误判, got: {err_msg!r}"
            )
