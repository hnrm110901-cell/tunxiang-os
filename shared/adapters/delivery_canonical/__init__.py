"""shared/adapters/delivery_canonical — 外卖订单 canonical schema 转换器

Sprint E1 交付：把 5 个平台（美团/饿了么/抖音/小红书/微信）千差万别的订单
payload 规范化到统一的 CanonicalDeliveryOrder，下游分析 / Agent / BI 只认
canonical，不碰平台。

典型使用：

    from shared.adapters.delivery_canonical import transform

    canonical = transform("meituan", raw_payload, tenant_id="uuid")
    # 写入 canonical_delivery_orders 表

如需自定义 transformer：

    from shared.adapters.delivery_canonical import (
        CanonicalTransformer,
        CanonicalDeliveryOrder,
        register_transformer,
    )

    class MyPlatformTransformer(CanonicalTransformer):
        platform = "my_platform"
        def transform(self, raw, tenant_id) -> CanonicalDeliveryOrder: ...

    register_transformer(MyPlatformTransformer())
"""

# 触发默认 transformer 注册（副作用导入）
from . import transformers  # noqa: F401
from .base import (
    CanonicalDeliveryItem,
    CanonicalDeliveryOrder,
    CanonicalTransformer,
    TransformationError,
)
from .registry import (
    get_transformer,
    list_supported_platforms,
    register_transformer,
    transform,
)

__all__ = [
    "CanonicalDeliveryItem",
    "CanonicalDeliveryOrder",
    "CanonicalTransformer",
    "TransformationError",
    "get_transformer",
    "list_supported_platforms",
    "register_transformer",
    "transform",
]
