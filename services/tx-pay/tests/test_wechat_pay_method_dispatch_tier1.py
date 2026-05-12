"""微信支付 channel.pay() 方法分发 Tier 1 测试（餐厅场景）

场景动机：
  WechatPayChannel.pay() 真实模式下调用 self._service.create_jsapi_order(...)，
  但 WechatPayService 实际只有 create_prepay 方法（没有 create_jsapi_order）。
  收银员一旦在生产环境扫顾客微信付款码，pay() 立即 AttributeError → 收款链路断 → 顾客付不了款。

涉及 Tier 1 路径：支付补偿 Saga（§17）— TDD 红绿双 commit。

本 PR 仅做 surgical bug 修复，不补完 APP/H5/Native 完整支持（留 follow-up issue）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.tx_pay.src.channels.base import (
    PaymentRequest,
    PayMethod,
    TradeType,
)
from services.tx_pay.src.channels.wechat import WechatPayChannel


class TestWechatPayMethodDispatchTier1:
    """微信 channel.pay() 真实模式方法调用 — Tier 1 防 AttributeError"""

    @pytest.mark.asyncio
    async def test_jsapi_pay_calls_create_prepay_not_create_jsapi_order(self) -> None:
        """场景：服务员让顾客在微信小程序内付款（JSAPI），真实模式下必须调
        WechatPayService.create_prepay（实际存在的方法），不能调
        create_jsapi_order（未定义，调即 AttributeError → 顾客付不了款）。
        """
        channel = WechatPayChannel(notify_url="http://test/notify")

        # 注入一个真实存在但 spec 受限的 fake service：只暴露 create_prepay
        fake_service = AsyncMock()
        fake_service.create_prepay = AsyncMock(
            return_value={
                "timeStamp": "1747028400",
                "nonceStr": "nonce123",
                "package": "prepay_id=wx_test_xxxx",
                "signType": "RSA",
                "paySign": "fake_pay_sign",
            }
        )
        # 显式 raise 在 create_jsapi_order 上以暴露老 bug 路径
        fake_service.create_jsapi_order.side_effect = AttributeError(
            "'WechatPayService' object has no attribute 'create_jsapi_order'"
        )
        channel._service = fake_service

        request = PaymentRequest(
            tenant_id="test_tenant",
            store_id="test_store",
            order_id="test_order",
            amount_fen=8800,
            method=PayMethod.WECHAT,
            trade_type=TradeType.JSAPI,
            openid="test_openid",
            description="桌台 A1 结账",
        )

        result = await channel.pay(request)

        # 验证 channel 调了正确的方法（create_prepay 被调用一次）
        fake_service.create_prepay.assert_awaited_once()
        # 验证错误方法（旧 bug 路径）未被调用
        fake_service.create_jsapi_order.assert_not_called()

        # 业务断言：返回合法 PaymentResult，channel_data 含 prepay 参数
        assert result.amount_fen == 8800
        assert "package" in result.channel_data
        assert result.channel_data["package"].startswith("prepay_id=")
