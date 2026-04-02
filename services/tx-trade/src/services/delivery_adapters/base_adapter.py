"""外卖平台适配器基类 — 定义统一接口和数据模型"""
from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────
# 统一数据模型
# ─────────────────────────────────────────────────────────────────

class DeliveryOrderItem(BaseModel):
    """外卖订单商品行（统一格式）"""
    platform_item_id: str = Field(..., description="平台 SKU ID")
    name: str = Field(..., description="商品名称")
    qty: int = Field(..., ge=1, description="数量")
    unit_price_fen: int = Field(..., ge=0, description="单价（分）")
    spec: Optional[str] = Field(None, description="规格/口味备注")
    total_fen: int = Field(..., ge=0, description="小计（分）= qty × unit_price_fen")


class DeliveryOrder(BaseModel):
    """统一外卖订单格式（所有平台解析后均转换为此格式）"""
    platform: str = Field(..., description="平台标识：meituan / eleme / douyin")
    platform_order_id: str = Field(..., description="平台原始订单号")
    status: str = Field(default="pending", description="初始状态")
    items: list[DeliveryOrderItem] = Field(default_factory=list)
    total_fen: int = Field(..., ge=0, description="订单总金额（分）")
    delivery_fee_fen: int = Field(default=0, ge=0, description="配送费（分）")
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    delivery_address: Optional[str] = None
    estimated_delivery_at: Optional[datetime] = None
    raw_payload: dict = Field(default_factory=dict, description="平台原始 payload")


# ─────────────────────────────────────────────────────────────────
# 抽象基类
# ─────────────────────────────────────────────────────────────────

class BaseDeliveryAdapter(ABC):
    """外卖平台适配器基类 — 所有平台必须实现此接口"""

    platform: str = ""  # 子类覆盖

    def __init__(self, app_id: str, app_secret: str, shop_id: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.shop_id = shop_id

    @abstractmethod
    def parse_order(self, raw: dict) -> DeliveryOrder:
        """将平台原始 payload 解析为统一 DeliveryOrder 格式"""
        ...

    @abstractmethod
    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """验证平台推送的签名，防止伪造请求"""
        ...

    @abstractmethod
    async def confirm_order(self, platform_order_id: str) -> bool:
        """调用平台 API 确认接单"""
        ...

    @abstractmethod
    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """调用平台 API 拒单"""
        ...

    # ── 工具方法 ──────────────────────────────────────────────────

    def _hmac_sha256(self, key: str, data: str) -> str:
        """通用 HMAC-SHA256 签名计算"""
        return hmac.new(
            key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _hmac_md5(self, key: str, data: str) -> str:
        """通用 HMAC-MD5 签名计算（部分平台使用）"""
        return hmac.new(
            key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.md5,
        ).hexdigest()
