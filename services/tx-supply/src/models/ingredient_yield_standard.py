"""商品出料率标准库 ORM + Pydantic Schema（PRD-06 / Tier 1 毛利底线）

ORM（SQLAlchemy 2.0）：
  IngredientYieldStandard       — 出料率标准主表（含季节差异 + 二级审批）

Pydantic V2 Schema：
  Create / Update / Read 模型 + Approve 请求体 + CalcPurchaseQty 请求/响应

枚举：
  Season — spring / summer / autumn / winter / all
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# 枚举（与 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────────────────────


class Season(str, Enum):
    """季节差异（春菠菜出料率 65% / 夏菠菜 50%）"""

    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    ALL = "all"  # 通用（无季节差异）


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class IngredientYieldStandard(TenantBase):
    """商品出料率标准（ingredient_yield_standards）"""

    __tablename__ = "ingredient_yield_standards"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    process_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    yield_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    season: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.0")
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class YieldStandardCreate(_BaseSchema):
    """创建出料率标准（草稿态 — approved_by 为 NULL）"""

    yield_rate: Decimal = Field(gt=0, le=1, description="出料率 (0, 1]，如 0.6 表示 60%")
    season: Season = Season.ALL
    tolerance_pct: Decimal = Field(default=Decimal("5.0"), ge=0, le=100)
    effective_from: date
    effective_to: Optional[date] = None
    process_id: Optional[str] = None
    notes: Optional[str] = None


class YieldStandardUpdate(_BaseSchema):
    """更新出料率标准（仅未审批草稿可更新）"""

    yield_rate: Optional[Decimal] = Field(default=None, gt=0, le=1)
    season: Optional[Season] = None
    tolerance_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    process_id: Optional[str] = None
    notes: Optional[str] = None


class YieldStandardRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    ingredient_id: uuid.UUID
    process_id: Optional[uuid.UUID]
    yield_rate: Decimal
    season: str
    effective_from: date
    effective_to: Optional[date]
    tolerance_pct: Decimal
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ApproveRequest(_BaseSchema):
    """二级审批请求"""

    approver_id: str = Field(..., description="审批人 ID（必须 != created_by）")


class CalcPurchaseQtyRequest(_BaseSchema):
    """BOM 反算购买量请求（输入净菜量 → 输出毛菜采购量）"""

    ingredient_id: str
    required_net_qty_kg: Decimal = Field(gt=0, description="所需净菜量 kg")
    season: Season = Season.ALL
    today: Optional[date] = None


class CalcPurchaseQtyResponse(_BaseSchema):
    ingredient_id: str
    required_net_qty_kg: Decimal
    purchase_qty_kg: Decimal
    standard_id: Optional[str]
    yield_rate: Optional[Decimal]
    season_matched: Optional[str]
    anomaly_detected: bool
