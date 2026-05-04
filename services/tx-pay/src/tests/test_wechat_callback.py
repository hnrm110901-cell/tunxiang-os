"""test_wechat_callback.py — 微信支付回调路由测试

覆盖端点：
  POST /api/v1/pay/callback/wechat

回调逻辑：
  - 从 deps.get_channel_registry() 获取 registry
  - registry.get("wechat_direct") 获取微信渠道实例（非 async 调用）
  - channel.verify_callback(headers, body) 验证签名并解析（async 调用）
  - 成功 → 发射 payment.confirmed 事件 → 返回 {"code": "SUCCESS"}
  - 验签失败 → 返回 400
  - NotImplementedError（Mock 模式）→ 直接返回 SUCCESS

测试策略：
  通过 patch("src.deps.get_channel_registry") 注入 mock registry。
  注意：registry.get() 在路由中不加 await，所以必须是普通 MagicMock。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from src.channels.base import CallbackPayload, PayStatus


class TestWechatCallback:
    """POST /api/v1/pay/callback/wechat"""

    CALLBACK_URL = "/api/v1/pay/callback/wechat"
    VALID_BODY = b'{"id":"test-event-id","create_time":"2025-01-01T00:00:00+08:00","resource_type":"encrypt-resource","resource":{"algorithm":"AEAD_AES_256_GCM","ciphertext":"test-cipher","nonce":"test-nonce","associated_data":"test-ad"}}'

    @pytest.mark.asyncio
    async def test_callback_success(self, callback_client: AsyncClient):
        """有效回调 → verify_callback 成功 → 返回 200 {"code": "SUCCESS"}"""

        # channel.verify_callback 是 async 调用
        mock_channel = MagicMock()
        mock_channel.verify_callback = AsyncMock(
            return_value=CallbackPayload(
                payment_id="pay_wx_001", trade_no="txn_mock_001",
                status=PayStatus.SUCCESS, amount_fen=8800,
            )
        )

        # registry.get 是普通属性访问（路由器里不加 await）
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_channel

        # get_channel_registry 是 async 调用
        async def _get_registry():
            return mock_registry

        # emit_payment_confirmed 会触发 Python 3.9 不兼容的 import，patch 掉
        with patch("src.deps.get_channel_registry", _get_registry), \
             patch("src.events.emit_payment_confirmed", new=AsyncMock()):
            resp = await callback_client.post(
                self.CALLBACK_URL,
                content=self.VALID_BODY,
                headers={
                    "Wechatpay-Signature": "valid-signature",
                    "Wechatpay-Serial": "valid-serial",
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"code": "SUCCESS"}

    @pytest.mark.asyncio
    async def test_callback_invalid_signature(self, callback_client: AsyncClient):
        """验签失败 → 返回 400 {"code": "FAIL"}"""
        mock_channel = MagicMock()
        mock_channel.verify_callback = AsyncMock(side_effect=ValueError("验签失败"))

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_channel

        async def _get_registry():
            return mock_registry

        with patch("src.deps.get_channel_registry", _get_registry):
            resp = await callback_client.post(
                self.CALLBACK_URL,
                content=b"{}",
                headers={
                    "Wechatpay-Signature": "bad-signature",
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 400
        payload = resp.json()
        assert payload["code"] == "FAIL"

    @pytest.mark.asyncio
    async def test_callback_mock_mode(self, callback_client: AsyncClient):
        """Mock 模式 → verify_callback 抛出 NotImplementedError → 返回 200 SUCCESS"""
        mock_channel = MagicMock()
        mock_channel.verify_callback = AsyncMock(
            side_effect=NotImplementedError("Mock 模式不支持回调验证")
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_channel

        async def _get_registry():
            return mock_registry

        with patch("src.deps.get_channel_registry", _get_registry):
            resp = await callback_client.post(
                self.CALLBACK_URL,
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"code": "SUCCESS"}

    @pytest.mark.asyncio
    async def test_callback_timeout_order(self, callback_client: AsyncClient):
        """超时订单回调 → verify_callback 返回 PENDING → 仍返回 200 SUCCESS"""
        mock_channel = MagicMock()
        mock_channel.verify_callback = AsyncMock(
            return_value=CallbackPayload(
                payment_id="pay_wx_timeout_001", trade_no="",
                status=PayStatus.PENDING, amount_fen=8800,
            )
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_channel

        async def _get_registry():
            return mock_registry

        with patch("src.deps.get_channel_registry", _get_registry), \
             patch("src.events.emit_payment_confirmed", new=AsyncMock()):
            resp = await callback_client.post(
                self.CALLBACK_URL,
                content=self.VALID_BODY,
                headers={
                    "Wechatpay-Signature": "valid-signature",
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"code": "SUCCESS"}
