"""DeliveryPublisher 基础定义 + 数据类

所有平台 Publisher 统一契约：
  · 输入 DishPublishSpec（canonical dish 规格）
  · 输出 PublishResult（platform_sku_id + status + error）

字段语义对齐 v286 `dish_publish_registry` + `dish_publish_tasks` 迁移。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────
# 枚举（对齐 v286 CHECK 约束）
# ─────────────────────────────────────────────────────────────


class PublishStatus(str, Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PAUSED = "paused"
    SOLD_OUT = "sold_out"
    UNPUBLISHED = "unpublished"
    ERROR = "error"


class PublishOperation(str, Enum):
    PUBLISH = "publish"
    UPDATE_PRICE = "update_price"
    UPDATE_STOCK = "update_stock"
    UPDATE_FULL = "update_full"
    PAUSE = "pause"
    RESUME = "resume"
    UNPUBLISH = "unpublish"


ALLOWED_PLATFORMS = frozenset(
    {"meituan", "eleme", "douyin", "xiaohongshu", "wechat", "other"}
)


class PublishError(Exception):
    """publisher 级别致命错误（签名失败 / 平台 API 封禁 / 参数非法）"""


# ─────────────────────────────────────────────────────────────
# DishPublishSpec — canonical dish 规格
# ─────────────────────────────────────────────────────────────


@dataclass
class DishPublishSpec:
    """一道菜要发布到某平台需要的全部信息（平台无关）"""

    dish_id: str
    name: str
    category: str  # 菜系分类，如 "川菜/热菜"
    price_fen: int
    # 可选
    description: Optional[str] = None
    original_price_fen: Optional[int] = None  # 划线价（促销显示用）
    stock: Optional[int] = None  # None = 不限库存
    image_urls: list[str] = field(default_factory=list)
    cover_image_url: Optional[str] = None
    # 规格 / 做法
    modifiers: list[dict[str, Any]] = field(default_factory=list)
    # 标签（辣度 / 推荐 / 新品）
    tags: list[str] = field(default_factory=list)
    # 包装 / 配送
    packaging_fee_fen: int = 0
    weight_g: Optional[int] = None
    # 营养 / 过敏原（抖音健康标签需要）
    allergens: list[str] = field(default_factory=list)
    calories_kcal: Optional[int] = None
    # 平台专属 override（如 meituan 需要 specId / eleme 需要 categoryChainId）
    platform_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price_fen < 0:
            raise PublishError(
                f"price_fen 必须 >=0，收到 {self.price_fen}"
            )
        if not self.name.strip():
            raise PublishError("name 不能为空")
        if not self.dish_id.strip():
            raise PublishError("dish_id 不能为空")
        if self.stock is not None and self.stock < 0:
            raise PublishError(f"stock 不能为负，收到 {self.stock}")

    def override_for(self, platform: str) -> dict[str, Any]:
        """获取某平台的 override 字段（平台需要的额外参数）"""
        return self.platform_overrides.get(platform, {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "dish_id": self.dish_id,
            "name": self.name,
            "category": self.category,
            "price_fen": self.price_fen,
            "description": self.description,
            "original_price_fen": self.original_price_fen,
            "stock": self.stock,
            "image_urls": self.image_urls,
            "cover_image_url": self.cover_image_url,
            "modifiers": self.modifiers,
            "tags": self.tags,
            "packaging_fee_fen": self.packaging_fee_fen,
            "weight_g": self.weight_g,
            "allergens": self.allergens,
            "calories_kcal": self.calories_kcal,
            "platform_overrides": self.platform_overrides,
        }


# ─────────────────────────────────────────────────────────────
# PublishResult — 发布结果
# ─────────────────────────────────────────────────────────────


@dataclass
class PublishResult:
    """Publisher 返回给 Orchestrator 的结果"""

    platform: str
    operation: PublishOperation
    status: PublishStatus  # published / paused / sold_out / unpublished / error
    ok: bool
    platform_sku_id: Optional[str] = None
    published_price_fen: Optional[int] = None
    published_stock: Optional[int] = None
    platform_response: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def success(
        cls,
        *,
        platform: str,
        operation: PublishOperation,
        status: PublishStatus,
        platform_sku_id: Optional[str] = None,
        published_price_fen: Optional[int] = None,
        published_stock: Optional[int] = None,
        platform_response: Optional[dict[str, Any]] = None,
    ) -> "PublishResult":
        return cls(
            platform=platform,
            operation=operation,
            status=status,
            ok=True,
            platform_sku_id=platform_sku_id,
            published_price_fen=published_price_fen,
            published_stock=published_stock,
            platform_response=platform_response or {},
        )

    @classmethod
    def failure(
        cls,
        *,
        platform: str,
        operation: PublishOperation,
        error_message: str,
        error_code: Optional[str] = None,
        platform_response: Optional[dict[str, Any]] = None,
    ) -> "PublishResult":
        return cls(
            platform=platform,
            operation=operation,
            status=PublishStatus.ERROR,
            ok=False,
            platform_response=platform_response or {},
            error_message=error_message,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "operation": self.operation.value,
            "status": self.status.value,
            "ok": self.ok,
            "platform_sku_id": self.platform_sku_id,
            "published_price_fen": self.published_price_fen,
            "published_stock": self.published_stock,
            "platform_response": self.platform_response,
            "error_message": self.error_message,
            "error_code": self.error_code,
        }


# ─────────────────────────────────────────────────────────────
# DeliveryPublisher ABC
# ─────────────────────────────────────────────────────────────


class DeliveryPublisher(ABC):
    """所有平台 Publisher 的基类。

    子类必须声明 `platform` 类属性 + 实现 7 个操作方法（或可选实现核心 4 个）。
    默认 ABC 只强制 publish / update_price / update_stock / unpublish 四个，
    其他用默认实现（不支持则报错）。
    """

    platform: str = ""

    # ── 必需 ──

    @abstractmethod
    async def publish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        """首次上架。返回 platform_sku_id"""

    @abstractmethod
    async def update_price(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        price_fen: int,
        original_price_fen: Optional[int] = None,
    ) -> PublishResult: ...

    @abstractmethod
    async def update_stock(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int],
    ) -> PublishResult: ...

    @abstractmethod
    async def unpublish(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult: ...

    # ── 可选（默认合成）──

    async def pause(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
    ) -> PublishResult:
        """停售（保留 SKU，仅设为不可售）—— 默认实现调用 update_stock(0)"""
        return await self.update_stock(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            stock=0,
        )

    async def resume(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        stock: Optional[int] = None,
    ) -> PublishResult:
        """恢复售卖 —— 默认调用 update_stock(stock or None)"""
        return await self.update_stock(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            stock=stock,
        )

    async def update_full(
        self,
        *,
        tenant_id: str,
        platform_shop_id: str,
        platform_sku_id: str,
        spec: DishPublishSpec,
    ) -> PublishResult:
        """全量更新（价 + 库存 + metadata）—— 默认顺序调 update_price + update_stock"""
        price_result = await self.update_price(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            price_fen=spec.price_fen,
            original_price_fen=spec.original_price_fen,
        )
        if not price_result.ok:
            return price_result
        stock_result = await self.update_stock(
            tenant_id=tenant_id,
            platform_shop_id=platform_shop_id,
            platform_sku_id=platform_sku_id,
            stock=spec.stock,
        )
        # 合并：以 stock_result 为准（包含最新价 + 最新库存）
        if not stock_result.ok:
            return stock_result
        return PublishResult.success(
            platform=self.platform,
            operation=PublishOperation.UPDATE_FULL,
            status=PublishStatus.PUBLISHED,
            platform_sku_id=platform_sku_id,
            published_price_fen=price_result.published_price_fen,
            published_stock=stock_result.published_stock,
            platform_response={
                "price": price_result.platform_response,
                "stock": stock_result.platform_response,
            },
        )
