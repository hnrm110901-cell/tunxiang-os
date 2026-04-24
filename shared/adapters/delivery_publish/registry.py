"""Publisher 注册表（对称 canonical 的 registry）"""
from __future__ import annotations

import logging
from typing import Optional

from .base import (
    ALLOWED_PLATFORMS,
    DeliveryPublisher,
    DishPublishSpec,
    PublishError,
    PublishOperation,
    PublishResult,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, DeliveryPublisher] = {}


def register_publisher(publisher: DeliveryPublisher) -> None:
    """注册 publisher。重名覆盖（允许测试环境 monkey patch）"""
    if publisher.platform not in ALLOWED_PLATFORMS:
        raise ValueError(
            f"publisher.platform {publisher.platform!r} 不在 ALLOWED_PLATFORMS 中"
        )
    if publisher.platform in _REGISTRY:
        logger.warning(
            "publisher_override", extra={"platform": publisher.platform}
        )
    _REGISTRY[publisher.platform] = publisher


def get_publisher(platform: str) -> DeliveryPublisher:
    publisher = _REGISTRY.get(platform)
    if publisher is None:
        raise PublishError(
            f"找不到 platform={platform!r} 的 publisher。已注册："
            f"{sorted(_REGISTRY.keys())}"
        )
    return publisher


def list_registered_publishers() -> list[str]:
    return sorted(_REGISTRY.keys())


async def publish_to_platform(
    *,
    platform: str,
    tenant_id: str,
    platform_shop_id: str,
    spec: DishPublishSpec,
    operation: PublishOperation = PublishOperation.PUBLISH,
    platform_sku_id: Optional[str] = None,
) -> PublishResult:
    """便捷函数：按 operation 调用对应方法

    - PUBLISH: 首次上架，不需要 platform_sku_id
    - UPDATE_PRICE/UPDATE_STOCK/PAUSE/RESUME/UNPUBLISH: 需要 platform_sku_id
    - UPDATE_FULL: 全量更新
    """
    publisher = get_publisher(platform)

    if operation == PublishOperation.PUBLISH:
        return await publisher.publish(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            spec=spec,
        )

    if not platform_sku_id:
        raise PublishError(
            f"operation={operation.value} 需要 platform_sku_id"
        )

    if operation == PublishOperation.UPDATE_PRICE:
        return await publisher.update_price(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            price_fen=spec.price_fen,
            original_price_fen=spec.original_price_fen,
        )
    if operation == PublishOperation.UPDATE_STOCK:
        return await publisher.update_stock(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            stock=spec.stock,
        )
    if operation == PublishOperation.UPDATE_FULL:
        return await publisher.update_full(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            spec=spec,
        )
    if operation == PublishOperation.PAUSE:
        return await publisher.pause(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
        )
    if operation == PublishOperation.RESUME:
        return await publisher.resume(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            stock=spec.stock,
        )
    if operation == PublishOperation.UNPUBLISH:
        return await publisher.unpublish(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
        )
    raise PublishError(f"未知 operation: {operation}")
