"""渠道注册表 — 管理所有支付渠道实例的生命周期

使用方式：
    registry = ChannelRegistry()
    registry.register(WechatPayChannel(config))
    registry.register(LakalaChannel(config))

    channel = registry.get("wechat")
    channel = registry.find(method=PayMethod.WECHAT, trade_type=TradeType.JSAPI)
"""
from __future__ import annotations

from typing import Optional

import structlog

from .base import BasePaymentChannel, PayMethod, TradeType

logger = structlog.get_logger(__name__)


class ChannelRegistry:
    """支付渠道注册表

    维护 channel_name → channel_instance 的映射。
    支持按 (method, trade_type) 查找最匹配的渠道。
    """

    def __init__(self) -> None:
        self._channels: dict[str, BasePaymentChannel] = {}

    def register(self, channel: BasePaymentChannel) -> None:
        """注册渠道实例"""
        if not channel.channel_name:
            raise ValueError("channel_name 不能为空")
        self._channels[channel.channel_name] = channel
        logger.info(
            "payment_channel_registered",
            channel=channel.channel_name,
            methods=[m.value for m in channel.supported_methods],
            trade_types=[t.value for t in channel.supported_trade_types],
        )

    def get(self, channel_name: str) -> BasePaymentChannel:
        """按名称获取渠道实例"""
        channel = self._channels.get(channel_name)
        if channel is None:
            raise KeyError(f"未注册的支付渠道: {channel_name}")
        return channel

    def find(
        self,
        method: PayMethod,
        trade_type: TradeType,
    ) -> Optional[BasePaymentChannel]:
        """按支付方式和交易类型查找渠道

        返回第一个匹配的渠道（通常由 RoutingEngine 决定优先级）。
        """
        for channel in self._channels.values():
            if channel.supports(method, trade_type):
                return channel
        return None

    def list_channels(self) -> list[dict]:
        """列出所有已注册渠道"""
        return [
            {
                "name": ch.channel_name,
                "methods": [m.value for m in ch.supported_methods],
                "trade_types": [t.value for t in ch.supported_trade_types],
            }
            for ch in self._channels.values()
        ]

    @property
    def channel_names(self) -> list[str]:
        return list(self._channels.keys())
