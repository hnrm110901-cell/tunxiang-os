"""5 平台 Publisher stub 实现

本 PR 仅提供 stub — 返回 deterministic fake platform_sku_id，方便上层服务层
和测试直接跑通端到端。真实 SDK 集成（OAuth / 签名 / 重试 / 限流）在后续各
平台 adapter PR 中替换。

Stub 行为：
  · 成功：生成 fake SKU id `{platform}_{dish_id[:8]}_{shop_id[:4]}`
  · 失败模拟：当 spec.dish_id 以 `FAIL_` 开头 → 返回 PublishResult.failure
  · 不限库存：stock=None 时返回 published_stock=9999（stub 用）

真实 publisher 会：
  · 调平台 API（签名 / token 刷新）
  · 处理 429 限流 + 重试
  · 错误码归一化
"""
from __future__ import annotations

import hashlib
from typing import Optional

from .base import (
    DeliveryPublisher,
    DishPublishSpec,
    PublishOperation,
    PublishResult,
    PublishStatus,
)
from .registry import register_publisher


def _fake_sku_id(platform: str, dish_id: str, shop_id: str) -> str:
    """生成 deterministic fake SKU id（dish_id + shop_id hash）"""
    h = hashlib.sha256(f"{dish_id}:{shop_id}".encode()).hexdigest()[:10]
    return f"{platform}_sku_{h}"


def _should_fail(dish_id: str) -> bool:
    """测试 hook：dish_id 以 FAIL_ 开头时模拟失败"""
    return dish_id.startswith("FAIL_")


# ─────────────────────────────────────────────────────────────
# 美团
# ─────────────────────────────────────────────────────────────


class MeituanPublisher(DeliveryPublisher):
    """美团 Publisher stub

    真实实现要点：
      · POST /api/v2/food 上架菜品
      · PUT /api/v2/food/{foodCode}/price 改价
      · PUT /api/v2/food/{foodCode}/stock 改库存
      · 需要 appAuthToken（每 7 天刷新）
    """

    platform = "meituan"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="meituan stub: 模拟失败",
                error_code="STUB_FAIL",
            )
        sku_id = _fake_sku_id(self.platform, spec.dish_id, platform_shop_id)
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED if stock > 0 else PublishStatus.SOLD_OUT,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "appPoiCode": platform_shop_id,
                "appFoodCode": sku_id,
                "foodName": spec.name,
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={
                "appFoodCode": platform_sku_id,
                "price": price_fen / 100,
                "originalPrice": (
                    original_price_fen / 100 if original_price_fen else None
                ),
            },
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={"appFoodCode": platform_sku_id, "stock": confirmed},
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={"appFoodCode": platform_sku_id, "deleted": True},
        )


# ─────────────────────────────────────────────────────────────
# 饿了么
# ─────────────────────────────────────────────────────────────


class ElemePublisher(DeliveryPublisher):
    """饿了么 Publisher stub

    真实实现要点：
      · eleme.product.item.create 上架
      · eleme.product.item.updatePrice
      · eleme.product.item.updateStock
      · 签名 HMAC-SHA256
    """

    platform = "eleme"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="eleme stub: 模拟失败",
                error_code="ITEM_CREATE_FAILED",
            )
        sku_id = _fake_sku_id(self.platform, spec.dish_id, platform_shop_id)
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED if stock > 0 else PublishStatus.SOLD_OUT,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "shopId": platform_shop_id,
                "itemId": sku_id,
                "name": spec.name,
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={"itemId": platform_sku_id, "price": price_fen},
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={"itemId": platform_sku_id, "stock": confirmed},
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={"itemId": platform_sku_id, "offline": True},
        )


# ─────────────────────────────────────────────────────────────
# 抖音
# ─────────────────────────────────────────────────────────────


class DouyinPublisher(DeliveryPublisher):
    """抖音 Publisher stub

    真实实现要点：
      · 抖音开放平台 /api/apps/order/product/create
      · 营养 / 过敏原标签必填（2025 监管）
    """

    platform = "douyin"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="douyin stub: 模拟失败",
                error_code="PRODUCT_AUDIT_FAILED",
            )
        sku_id = _fake_sku_id(self.platform, spec.dish_id, platform_shop_id)
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED if stock > 0 else PublishStatus.SOLD_OUT,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "poi_id": platform_shop_id,
                "product_id": sku_id,
                "audit_status": "passed",
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={"product_id": platform_sku_id, "price": price_fen},
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={"product_id": platform_sku_id, "stock": confirmed},
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={"product_id": platform_sku_id, "offline": True},
        )


# ─────────────────────────────────────────────────────────────
# 小红书
# ─────────────────────────────────────────────────────────────


class XiaohongshuPublisher(DeliveryPublisher):
    """小红书团购 Publisher stub

    小红书主要场景：到店团购券（非外卖）。publish 实际是"创建团购 SKU"。
    """

    platform = "xiaohongshu"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="xiaohongshu stub: 模拟失败",
                error_code="GROUP_BUY_CREATE_FAILED",
            )
        sku_id = _fake_sku_id(self.platform, spec.dish_id, platform_shop_id)
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "shop_code": platform_shop_id,
                "sku_id": sku_id,
                "group_buy_type": "single",
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={"sku_id": platform_sku_id, "price": price_fen},
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={"sku_id": platform_sku_id, "stock": confirmed},
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={"sku_id": platform_sku_id, "offline": True},
        )


# ─────────────────────────────────────────────────────────────
# 微信小程序
# ─────────────────────────────────────────────────────────────


class WechatPublisher(DeliveryPublisher):
    """微信小程序自营 Publisher（即内部 dishes 表写入，无真实外部 API）"""

    platform = "wechat"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="wechat stub: 模拟失败",
                error_code="INTERNAL_ERROR",
            )
        # 微信自营 SKU id = internal dish_id
        sku_id = spec.dish_id
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "dish_id": sku_id,
                "channel": "wechat_miniapp",
                "store_id": platform_shop_id,
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={"dish_id": platform_sku_id, "price": price_fen},
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={"dish_id": platform_sku_id, "stock": confirmed},
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={"dish_id": platform_sku_id, "hidden": True},
        )


# ─────────────────────────────────────────────────────────────
# GrabFood (马来西亚)
# ─────────────────────────────────────────────────────────────


class GrabFoodPublisher(DeliveryPublisher):
    """GrabFood Publisher stub

    GrabFood uses menu sync (POST /grabfood/v1/menu/sync) for full
    menu replacement. Individual item publish/update is not supported —
    all changes require a full menu sync.

    Real implementation notes:
      - OAuth2 client_credentials with scope "partner"
      - POST /grabfood/v1/menu/sync — full replacement (all items required)
      - Items not in payload are removed from GrabFood
      - Currencies are always MYR
      - UpdateStock is not supported individually; use full menu sync
    """

    platform = "grabfood"

    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        if _should_fail(spec.dish_id):
            return PublishResult.failure(
                platform=self.platform,
                operation=PublishOperation.PUBLISH,
                error_message="grabfood stub: simulated failure",
                error_code="MENU_SYNC_FAILED",
            )
        sku_id = _fake_sku_id(self.platform, spec.dish_id, platform_shop_id)
        stock = 9999 if spec.stock is None else spec.stock
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED if stock > 0 else PublishStatus.SOLD_OUT,
            platform_sku_id=sku_id,
            published_price_fen=spec.price_fen,
            published_stock=stock,
            platform_response={
                "merchantID": platform_shop_id,
                "itemCode": sku_id,
                "name": spec.name,
                "currency": "MYR",
            },
        )

    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_PRICE,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_fen,
            platform_response={
                "itemCode": platform_sku_id,
                "price": price_fen / 100,
                "currency": "MYR",
            },
        )

    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult:
        confirmed = 9999 if stock is None else stock
        status = PublishStatus.SOLD_OUT if confirmed == 0 else PublishStatus.PUBLISHED
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_STOCK,
            status=status,
            platform_sku_id=platform_sku_id,
            published_stock=confirmed,
            platform_response={
                "itemCode": platform_sku_id,
                "stock": confirmed,
                "note": "GrabFood uses full menu sync; individual stock updates may require sync_menu()",
            },
        )

    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UNPUBLISH,
            status=PublishStatus.UNPUBLISHED,
            platform_sku_id=platform_sku_id,
            platform_response={
                "itemCode": platform_sku_id,
                "merchantID": platform_shop_id,
                "hidden": True,
            },
        )


# ─────────────────────────────────────────────────────────────
# 默认注册
# ─────────────────────────────────────────────────────────────

register_publisher(MeituanPublisher())
register_publisher(ElemePublisher())
register_publisher(DouyinPublisher())
register_publisher(XiaohongshuPublisher())
register_publisher(WechatPublisher())
register_publisher(GrabFoodPublisher())
