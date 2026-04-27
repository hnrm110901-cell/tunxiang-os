"""shared/adapters/delivery_publish — 菜品一键发布（Sprint E2）

E1 是"入向"：平台 payload → canonical；E2 是"出向"：canonical dish →
平台 SKU。每个平台的 Publisher 封装各自的 SDK 调用，上层 Orchestrator
编排跨平台批量发布。

典型用法：

    from shared.adapters.delivery_publish import publish_to_platform

    result = await publish_to_platform(
        platform="meituan",
        tenant_id="...",
        dish_spec=DishPublishSpec(
            dish_id="...",
            name="鱼香肉丝",
            price_fen=2800,
            stock=100,
            ...,
        ),
        platform_shop_id="poi_xxx",
    )
    # result: PublishResult(platform_sku_id, status, error)

注入真实 SDK：

    from shared.adapters.delivery_publish import register_publisher

    class MeituanRealPublisher(DeliveryPublisher):
        platform = "meituan"
        def __init__(self, client): self.client = client
        async def publish(self, ...): ...

    register_publisher(MeituanRealPublisher(real_client))
"""

# 副作用导入：注册默认 stub publishers
from . import publishers  # noqa: F401
from .base import (
    DeliveryPublisher,
    DishPublishSpec,
    PublishOperation,
    PublishResult,
    PublishStatus,
)
from .registry import (
    get_publisher,
    list_registered_publishers,
    publish_to_platform,
    register_publisher,
)

__all__ = [
    "DeliveryPublisher",
    "DishPublishSpec",
    "PublishOperation",
    "PublishResult",
    "PublishStatus",
    "get_publisher",
    "list_registered_publishers",
    "publish_to_platform",
    "register_publisher",
]
