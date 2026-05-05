"""
外卖平台适配器工厂

通过平台标识获取对应的 DeliveryPlatformAdapter 实例。
支持平台：meituan, eleme, douyin, wechat, grabfood, amap, taobao
"""

from __future__ import annotations

from typing import Dict

import structlog

from .amap.src.adapter import AmapAdapter
from .delivery_platform_base import DeliveryPlatformAdapter
from .douyin.src.adapter import DouyinAdapter
from .eleme.src.adapter import ElemeAdapter
from .grabfood.src.adapter import GrabFoodDeliveryAdapter
from .taobao.src.adapter import TaobaoAdapter
from .wechat_delivery_adapter import WeChatDeliveryAdapter

logger = structlog.get_logger()

# 已注册的平台 → 适配器类映射
# meituan-saas 使用 importlib 懒加载（目录含连字符，无法用标准 import 导入）
_PLATFORM_REGISTRY: Dict[str, type] = {
    "meituan": None,  # 见 _get_adapter_class()
    "eleme": ElemeAdapter,
    "douyin": DouyinAdapter,
    "amap": AmapAdapter,
    "grabfood": GrabFoodDeliveryAdapter,
    "taobao": TaobaoAdapter,
    "wechat": WeChatDeliveryAdapter,
}


def _get_adapter_class(platform: str) -> type:
    """获取适配器类，处理 meituan-saas 连字符目录的特殊导入。"""
    if platform == "meituan":
        import importlib

        module = importlib.import_module("shared.adapters.meituan-saas.src.adapter")
        cls: type = module.MeituanSaasAdapter
        # 注册缓存
        _PLATFORM_REGISTRY["meituan"] = cls
        return cls

    adapter_cls = _PLATFORM_REGISTRY.get(platform)
    if adapter_cls is None:
        supported = ", ".join(sorted(_PLATFORM_REGISTRY.keys()))
        raise ValueError(f"未知的外卖平台: {platform}，支持的平台: {supported}")
    return adapter_cls


def get_delivery_adapter(
    platform: str,
    config: dict | None = None,
    **kwargs: object,
) -> DeliveryPlatformAdapter:
    """获取外卖平台适配器实例

    Args:
        platform: 平台标识 ("meituan" / "eleme" / "douyin")
        config: 适配器配置字典（优先），包含 app_key, app_secret 等特定平台参数
        **kwargs: 传递给适配器构造函数的参数（config 不存在时使用）

    Returns:
        对应平台的 DeliveryPlatformAdapter 实例

    Raises:
        ValueError: 未知的平台标识
    """
    adapter_cls = _get_adapter_class(platform)

    logger.info("delivery_adapter_created", platform=platform)
    if config is not None:
        return adapter_cls(config=config, **kwargs)  # type: ignore[call-arg]
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
