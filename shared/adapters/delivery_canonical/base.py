"""CanonicalDeliveryOrder + CanonicalTransformer 基础定义

所有字段语义对齐 v285 迁移（shared/db-migrations/versions/v285_canonical_delivery_orders.py）。
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────
# 枚举常量（与 v285 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────

ALLOWED_PLATFORMS = frozenset(
    {"meituan", "eleme", "douyin", "xiaohongshu", "wechat", "grabfood", "other"}
)
# NOTE: When adding new platforms to ALLOWED_PLATFORMS, the corresponding
# DB migration CHECK constraint on canonical_delivery_orders.platform
# (v285) must also be updated. See shared/db-migrations/versions/v285_*.py.

ALLOWED_ORDER_TYPES = frozenset(
    {"delivery", "pickup", "dine_in", "group_buy"}
)

ALLOWED_STATUSES = frozenset(
    {
        "pending",
        "accepted",
        "preparing",
        "dispatched",
        "delivering",
        "delivered",
        "completed",
        "cancelled",
        "refunded",
        "error",
    }
)


class TransformationError(Exception):
    """transformer 明确无法转换时抛出（缺字段 / 平台版本不支持 / 签名错误）"""


# ─────────────────────────────────────────────────────────────
# CanonicalDeliveryItem
# ─────────────────────────────────────────────────────────────


@dataclass
class CanonicalDeliveryItem:
    """canonical_delivery_items 一条"""

    platform_sku_id: Optional[str]
    dish_name_platform: str
    quantity: int
    unit_price_fen: int
    subtotal_fen: int
    discount_amount_fen: int = 0
    total_fen: int = 0
    modifiers: list[dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None
    line_no: int = 1
    # 内部映射（若已匹配 Dish）
    internal_dish_id: Optional[str] = None
    dish_name_canonical: Optional[str] = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise TransformationError(
                f"item.quantity 必须 >0，收到 {self.quantity}"
            )
        if self.unit_price_fen < 0:
            raise TransformationError(
                f"item.unit_price_fen 必须 >=0，收到 {self.unit_price_fen}"
            )
        # 自动算 subtotal / total（允许上游已填入）
        if self.subtotal_fen == 0:
            self.subtotal_fen = self.unit_price_fen * self.quantity
        if self.total_fen == 0:
            self.total_fen = max(0, self.subtotal_fen - self.discount_amount_fen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_sku_id": self.platform_sku_id,
            "dish_name_platform": self.dish_name_platform,
            "dish_name_canonical": self.dish_name_canonical,
            "internal_dish_id": self.internal_dish_id,
            "quantity": self.quantity,
            "unit_price_fen": self.unit_price_fen,
            "subtotal_fen": self.subtotal_fen,
            "discount_amount_fen": self.discount_amount_fen,
            "total_fen": self.total_fen,
            "modifiers": self.modifiers,
            "notes": self.notes,
            "line_no": self.line_no,
        }


# ─────────────────────────────────────────────────────────────
# CanonicalDeliveryOrder
# ─────────────────────────────────────────────────────────────


@dataclass
class CanonicalDeliveryOrder:
    """canonical_delivery_orders 一条 + 嵌套 items

    字段语义严格对齐 v285 迁移。DAO 层把本 dataclass 直接映射到 SQL 参数。
    """

    # ── 平台识别 ──
    tenant_id: str
    platform: str
    platform_order_id: str
    # ── 时间轴（placed_at 必需）──
    placed_at: datetime
    # ── 可选字段（dataclass 默认值）──
    canonical_order_no: Optional[str] = None  # 入库前由 service 生成
    platform_sub_type: Optional[str] = None
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    order_type: str = "delivery"
    status: str = "pending"
    platform_status_raw: Optional[str] = None
    # 顾客
    customer_name: Optional[str] = None
    customer_phone_masked: Optional[str] = None
    customer_address: Optional[str] = None
    customer_address_hash: Optional[str] = None
    # 金额（fen）
    gross_amount_fen: int = 0
    discount_amount_fen: int = 0
    platform_commission_fen: int = 0
    platform_subsidy_fen: int = 0
    delivery_fee_fen: int = 0
    delivery_cost_fen: int = 0
    packaging_fee_fen: int = 0
    tax_fen: int = 0
    tip_fen: int = 0
    paid_amount_fen: int = 0
    net_amount_fen: int = 0
    # 时间
    accepted_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    expected_delivery_at: Optional[datetime] = None
    # 保真
    raw_payload: dict[str, Any] = field(default_factory=dict)
    payload_sha256: Optional[str] = None
    platform_metadata: dict[str, Any] = field(default_factory=dict)
    transformation_errors: list[dict[str, Any]] = field(default_factory=list)
    canonical_version: int = 1
    ingested_by: str = "webhook"
    # items
    items: list[CanonicalDeliveryItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.platform not in ALLOWED_PLATFORMS:
            raise TransformationError(
                f"platform 非法：{self.platform!r}，合法值 {sorted(ALLOWED_PLATFORMS)}"
            )
        if self.order_type not in ALLOWED_ORDER_TYPES:
            raise TransformationError(
                f"order_type 非法：{self.order_type!r}"
            )
        if self.status not in ALLOWED_STATUSES:
            raise TransformationError(f"status 非法：{self.status!r}")
        if not self.platform_order_id:
            raise TransformationError("platform_order_id 必填")
        if self.placed_at is None:
            raise TransformationError("placed_at 必填")

        # 若上游未计算 payload_sha256，现在补
        if not self.payload_sha256 and self.raw_payload:
            self.payload_sha256 = compute_payload_sha256(self.raw_payload)

        # 若上游未算 net_amount_fen，用公式补
        if self.net_amount_fen == 0 and any(
            [
                self.gross_amount_fen,
                self.discount_amount_fen,
                self.platform_commission_fen,
                self.platform_subsidy_fen,
            ]
        ):
            self.net_amount_fen = (
                self.gross_amount_fen
                - self.discount_amount_fen
                - self.platform_commission_fen
                + self.platform_subsidy_fen
            )

    def add_transformation_error(
        self, field_name: str, raw_value: Any, reason: str
    ) -> None:
        """transformer 内部调用，记录非致命问题（字段缺失 / 格式异常）"""
        self.transformation_errors.append(
            {
                "field": field_name,
                "raw_value": str(raw_value)[:200],
                "reason": reason,
            }
        )

    def to_insert_params(self) -> dict[str, Any]:
        """转成 SQL INSERT 参数（不含 items）"""
        return {
            "tenant_id": self.tenant_id,
            "canonical_order_no": self.canonical_order_no,
            "platform": self.platform,
            "platform_order_id": self.platform_order_id,
            "platform_sub_type": self.platform_sub_type,
            "store_id": self.store_id,
            "brand_id": self.brand_id,
            "order_type": self.order_type,
            "status": self.status,
            "platform_status_raw": self.platform_status_raw,
            "customer_name": self.customer_name,
            "customer_phone_masked": self.customer_phone_masked,
            "customer_address": self.customer_address,
            "customer_address_hash": self.customer_address_hash,
            "gross_amount_fen": self.gross_amount_fen,
            "discount_amount_fen": self.discount_amount_fen,
            "platform_commission_fen": self.platform_commission_fen,
            "platform_subsidy_fen": self.platform_subsidy_fen,
            "delivery_fee_fen": self.delivery_fee_fen,
            "delivery_cost_fen": self.delivery_cost_fen,
            "packaging_fee_fen": self.packaging_fee_fen,
            "tax_fen": self.tax_fen,
            "tip_fen": self.tip_fen,
            "paid_amount_fen": self.paid_amount_fen,
            "net_amount_fen": self.net_amount_fen,
            "placed_at": self.placed_at,
            "accepted_at": self.accepted_at,
            "dispatched_at": self.dispatched_at,
            "delivered_at": self.delivered_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
            "expected_delivery_at": self.expected_delivery_at,
            "raw_payload": json.dumps(self.raw_payload, ensure_ascii=False),
            "payload_sha256": self.payload_sha256,
            "platform_metadata": json.dumps(
                self.platform_metadata, ensure_ascii=False
            ),
            "transformation_errors": json.dumps(
                self.transformation_errors, ensure_ascii=False
            ),
            "canonical_version": self.canonical_version,
            "ingested_by": self.ingested_by,
        }


# ─────────────────────────────────────────────────────────────
# CanonicalTransformer ABC
# ─────────────────────────────────────────────────────────────


class CanonicalTransformer(ABC):
    """所有平台 transformer 的基类。

    子类必须：
      · 声明 `platform` 类属性（与 ALLOWED_PLATFORMS 匹配）
      · 实现 `transform(raw, tenant_id) → CanonicalDeliveryOrder`

    可选覆盖：
      · `supports(raw) → bool` — 自动嗅探 payload 是否属于本 transformer
      · `version` — transformer 版本号（用于 canonical_version 字段）
    """

    platform: str = ""
    version: int = 1

    @abstractmethod
    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        """把平台 raw payload 转成 CanonicalDeliveryOrder。

        实现注意：
          · 保留 raw 到 `order.raw_payload`
          · 无法映射的字段用 `order.add_transformation_error(...)` 记录
          · 金额全部转 fen（整数），浮点需四舍五入 `int(round(v * 100))`
          · 时间戳统一 UTC-aware datetime
        """
        ...

    def supports(self, raw: dict[str, Any]) -> bool:
        """嗅探：如果 payload 看起来属于本 transformer，返 True。

        默认实现：检查 raw 中是否含本 platform 特有 key。
        子类可覆盖。
        """
        return False


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def compute_payload_sha256(payload: dict[str, Any]) -> str:
    """稳定序列化 payload 后计算 sha256（用于幂等 UNIQUE 约束）"""
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """手机号脱敏：138****5678"""
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 7:
        return "****"
    return f"{digits[:3]}****{digits[-4:]}"


def hash_address(address: Optional[str]) -> Optional[str]:
    """地址做稳定 hash（用于重复检测），不加盐（全租户共享空间）"""
    if not address:
        return None
    normalized = address.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def to_fen(amount: Any) -> int:
    """把浮点元 / 字符串 / 整数 统一转为 fen（整数分）

    规则：
      · int → 若 > 10000 视为已是 fen；否则视为元 * 100
        （边界粗略，transformer 应明确单位传入）
      · float → round(v * 100)
      · str → float(str)
      · None → 0
    """
    if amount is None:
        return 0
    if isinstance(amount, bool):
        return 0  # True/False 不是金额
    if isinstance(amount, int):
        # transformer 应该明确，不走启发式，原样返回视为已是 fen
        return amount
    if isinstance(amount, float):
        return int(round(amount * 100))
    if isinstance(amount, str):
        try:
            return int(round(float(amount) * 100))
        except (ValueError, TypeError):
            return 0
    return 0
