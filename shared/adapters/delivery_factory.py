"""
外卖平台适配器工厂

通过平台标识获取对应的 DeliveryPlatformAdapter 实例。
支持平台：meituan, eleme, douyin, wechat
"""

from typing import Dict

import structlog

from .delivery_platform_base import DeliveryPlatformAdapter
from .douyin_adapter import DouyinDeliveryAdapter
from .eleme_adapter import ElemeDeliveryAdapter
from .meituan_adapter import MeituanDeliveryAdapter
from .wechat_delivery_adapter import WeChatDeliveryAdapter

logger = structlog.get_logger()

# 已注册的平台 → 适配器类映射
_PLATFORM_REGISTRY: Dict[str, type] = {
    "meituan": MeituanDeliveryAdapter,
    "eleme": ElemeDeliveryAdapter,
    "douyin": DouyinDeliveryAdapter,
    "wechat": WeChatDeliveryAdapter,
}


def get_delivery_adapter(
    platform: str,
    **kwargs: object,
) -> DeliveryPlatformAdapter:
    """获取外卖平台适配器实例

    Args:
        platform: 平台标识 ("meituan" / "eleme" / "douyin")
        **kwargs: 传递给适配器构造函数的参数
            - app_key, app_secret, store_map, timeout 等

    Returns:
        对应平台的 DeliveryPlatformAdapter 实例

    Raises:
        ValueError: 未知的平台标识
    """
    adapter_cls = _PLATFORM_REGISTRY.get(platform)
    if adapter_cls is None:
        supported = ", ".join(sorted(_PLATFORM_REGISTRY.keys()))
        raise ValueError(f"未知的外卖平台: {platform}，支持的平台: {supported}")

    logger.info("delivery_adapter_created", platform=platform)
    return adapter_cls(**kwargs)  # type: ignore[call-arg]


def register_delivery_platform(
    platform: str,
    adapter_cls: type,
) -> None:
    """注册新的外卖平台适配器（扩展点）

    Args:
        platform: 平台标识
        adapter_cls: 适配器类（必须继承 DeliveryPlatformAdapter）
    """
    if not issubclass(adapter_cls, DeliveryPlatformAdapter):
        raise TypeError(f"{adapter_cls.__name__} 必须继承 DeliveryPlatformAdapter")
    _PLATFORM_REGISTRY[platform] = adapter_cls
    logger.info("delivery_platform_registered", platform=platform, cls=adapter_cls.__name__)
