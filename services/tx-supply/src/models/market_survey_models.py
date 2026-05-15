"""Market Survey ORM + Pydantic Schema（PRD-13 sub-A / Phase 2 W11 / T2 normal）

ORM（SQLAlchemy 2.0 typed Mapped[]）:
  MarketSurvey            — 调研主表 (employee_id surveyor + market_type + status 三态)
  MarketSurveyItem        — 调研明细 (单位价 + qty_per_unit + 自由文本 ingredient 兜底)
  MarketSurveyPhoto       — 独立照片表 (AI Vision OCR ready, 含 caption/exif_meta JSONB)

Pydantic V2 Schema:
  MarketType / SurveyStatus enum (与 v435 CHECK 约束对齐)
  MarketSurveyCreate / Update / Read
  MarketSurveyItemCreate / Update / Read
  MarketSurveyPhotoCreate / Update / Read
  MarketSurveyDetail      — 主表 + items + photos 聚合输出

业务流：
  早市 5 点创始人/采购总监带 iPad 出门 →
  draft 调研建表 (location_name='马王堆海鲜批发市场' / market_type=wholesale) →
  逐 item 录入 (拍照, qty/unit, unit_price_fen 整数分) →
  提交 status=submitted →
  采购总监审核 status=verified →
  AI 训练池消费 verified 数据 (sub-C tx-analytics)

设计要点 (创始人 AskUserQuestion 锁定):
  - D1 surveyor_id = employee_id (RLS via tenant)
  - D2 photos 独立表关联 (vs JSONB[] 直存) — AI Vision OCR 标注 ready
  - D3 unit_price_fen + qty_per_unit (单位价格) — AI 训练直接消费, BOM unit 匹配
  - D4 status 三态: draft / submitted / verified
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────────────────────────────────────
# 枚举 (与 v435 CHECK 约束对齐)
# ─────────────────────────────────────────────────────────────────────────────


class MarketType(str, Enum):
    """市场类型 — 创始人 AskUserQuestion 锁定支持 4 种."""

    WHOLESALE = "wholesale"  # 批发市场 (马王堆海鲜批发市场)
    WET_MARKET = "wet_market"  # 菜市场/早市
    SUPERMARKET = "supermarket"  # 超市/卖场
    OTHER = "other"  # 其他 (产地直采 / 临时摊位)


class SurveyStatus(str, Enum):
    """调研工作流状态 — 创始人 AskUserQuestion 锁定三态."""

    DRAFT = "draft"  # 移动端起草, 尚未提交
    SUBMITTED = "submitted"  # 已提交 (训练池候选)
    VERIFIED = "verified"  # 采购总监审核合格 (进训练池)


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class MarketSurvey(TenantBase):
    """market_surveys — 调研主表 (每次出门一条记录)

    surveyor_id 是 employee_id (跨服务逻辑 FK, 不加 DB FK 约束 / RLS via tenant).
    """

    __tablename__ = "market_surveys"

    surveyor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    market_type: Mapped[str] = mapped_column(String(20), nullable=False)
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    surveyed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class MarketSurveyItem(TenantBase):
    """market_survey_items — 调研明细 (一调研 N items)

    ingredient_id 可选 (NULL = 自由文本 ingredient, 系统无对应食材时兜底).
    ingredient_name 必填 (即便有 ingredient_id 也冗余存名 — 食材改名时历史价稳定).
    """

    __tablename__ = "market_survey_items"

    survey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_price_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="斤")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 仅 created_at, 明细无 updated_at (TenantBase 提供 created_at + is_deleted)


class MarketSurveyPhoto(TenantBase):
    """market_survey_photos — 独立照片表 (AI Vision OCR ready)

    item_id NULL = 调研封面图 (主表级别).
    item_id NOT NULL = 单 item 详细照 (价签 / 食材 / 陈列).
    exif_meta JSONB 存设备 GPS / 拍摄时间 / 相机参数 (AI 标注用).
    """

    __tablename__ = "market_survey_photos"

    survey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    photo_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    exif_meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — 调研主表 CRUD
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MarketSurveyCreate(_BaseSchema):
    """新建调研."""

    surveyor_id: uuid.UUID
    market_type: MarketType
    location_name: str = Field(min_length=1, max_length=200)
    surveyed_at: datetime
    notes: Optional[str] = Field(default=None, max_length=2000)


class MarketSurveyUpdate(_BaseSchema):
    """更新调研 — status 单独走 transition endpoint, 不在此路径."""

    market_type: Optional[MarketType] = None
    location_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    surveyed_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class MarketSurveyRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    surveyor_id: uuid.UUID
    market_type: str
    location_name: str
    surveyed_at: datetime
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — 调研明细 CRUD
# ─────────────────────────────────────────────────────────────────────────────


class MarketSurveyItemCreate(_BaseSchema):
    """新建调研明细."""

    ingredient_id: Optional[uuid.UUID] = None
    ingredient_name: str = Field(min_length=1, max_length=200)
    unit_price_fen: int = Field(ge=0, description="单位价格 (分, 整数)")
    qty_per_unit: Decimal = Field(default=Decimal("1"), gt=0, description="单位规格 (1斤/1个/1箱)")
    unit: str = Field(default="斤", min_length=1, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=1000)


class MarketSurveyItemUpdate(_BaseSchema):
    """更新调研明细."""

    ingredient_id: Optional[uuid.UUID] = None
    ingredient_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    unit_price_fen: Optional[int] = Field(default=None, ge=0)
    qty_per_unit: Optional[Decimal] = Field(default=None, gt=0)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=1000)


class MarketSurveyItemRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    survey_id: uuid.UUID
    ingredient_id: Optional[uuid.UUID]
    ingredient_name: str
    unit_price_fen: int
    qty_per_unit: Decimal
    unit: str
    notes: Optional[str]
    created_at: datetime
    is_deleted: bool


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — 照片 CRUD
# ─────────────────────────────────────────────────────────────────────────────


class MarketSurveyPhotoCreate(_BaseSchema):
    """新建调研照片 (caller 传入已上传到 COS 的 URL).

    item_id NULL = 调研封面图; 非 NULL = 单 item 价签/陈列照.
    sub-B 移动端实现: 拍照 → COS upload → 拿 URL 调本接口落记录.
    """

    item_id: Optional[uuid.UUID] = None
    photo_url: str = Field(min_length=1, max_length=1000)
    caption: Optional[str] = Field(default=None, max_length=500)
    exif_meta: Optional[dict] = None
    uploaded_at: Optional[datetime] = None


class MarketSurveyPhotoUpdate(_BaseSchema):
    """更新照片 — 仅 caption / exif_meta (URL/uploaded_at 不可改)."""

    caption: Optional[str] = Field(default=None, max_length=500)
    exif_meta: Optional[dict] = None


class MarketSurveyPhotoRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    survey_id: uuid.UUID
    item_id: Optional[uuid.UUID]
    photo_url: str
    caption: Optional[str]
    exif_meta: Optional[dict]
    uploaded_at: datetime
    created_at: datetime
    is_deleted: bool


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas — 聚合详情 + status 转换
# ─────────────────────────────────────────────────────────────────────────────


class MarketSurveyDetail(_BaseSchema):
    """主表 + items + photos 聚合输出 (UI 详情页)."""

    survey: MarketSurveyRead
    items: list[MarketSurveyItemRead]
    photos: list[MarketSurveyPhotoRead]


class StatusTransitionRequest(_BaseSchema):
    """status 转换请求 (draft→submitted / submitted→verified).

    限定合法转换:
      draft     → submitted (移动端提交)
      submitted → verified  (采购总监审核合格)
      submitted → draft     (退回起草)
      verified  → (终态, 不可改)
    """

    target_status: SurveyStatus
    notes: Optional[str] = Field(default=None, max_length=1000)


__all__ = [
    "MarketType",
    "SurveyStatus",
    "MarketSurvey",
    "MarketSurveyItem",
    "MarketSurveyPhoto",
    "MarketSurveyCreate",
    "MarketSurveyUpdate",
    "MarketSurveyRead",
    "MarketSurveyItemCreate",
    "MarketSurveyItemUpdate",
    "MarketSurveyItemRead",
    "MarketSurveyPhotoCreate",
    "MarketSurveyPhotoUpdate",
    "MarketSurveyPhotoRead",
    "MarketSurveyDetail",
    "StatusTransitionRequest",
]
