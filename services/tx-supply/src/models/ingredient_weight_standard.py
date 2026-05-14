"""商品扣秤标准库 ORM + Pydantic Schema（PRD-02 / Tier 1 毛利底线）

ORM（SQLAlchemy 2.0）：
  IngredientWeightStandard       — 扣秤标准主表（含二级审批 approved_by / approved_at）
  ReceivingWeightDeduction       — 收货扣秤日志（关联 receiving_order_items，不动 ontology）

Pydantic V2 Schema：
  Create / Update / Read 模型 + Approve 请求体

枚举：
  DeductType      — ice / packaging / leaves / stem / other
  DeductMethod    — percentage / fixed_kg
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# 枚举（与 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────────────────────


class DeductType(str, Enum):
    """扣秤项类目"""

    ICE = "ice"  # 冰块
    PACKAGING = "packaging"  # 塑料袋 / 箱
    LEAVES = "leaves"  # 菜叶损耗
    STEM = "stem"  # 茎梗损耗
    OTHER = "other"


class DeductMethod(str, Enum):
    """扣秤方法"""

    PERCENTAGE = "percentage"  # 按毛重百分比扣（deduct_value 是 % 数值，如 8.0 = 8%）
    FIXED_KG = "fixed_kg"  # 按固定 kg 扣（deduct_value 是 kg）


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class IngredientWeightStandard(TenantBase):
    """商品扣秤标准（ingredient_weight_standards）"""

    __tablename__ = "ingredient_weight_standards"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deduct_type: Mapped[str] = mapped_column(String(20), nullable=False)
    deduct_method: Mapped[str] = mapped_column(String(20), nullable=False)
    deduct_value: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("2.0")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class ReceivingWeightDeduction(TenantBase):
    """收货扣秤日志（receiving_weight_deductions）

    每次收货应用扣秤时写一行 — 记录 gross / net / 应用的 deductions 明细。
    """

    __tablename__ = "receiving_weight_deductions"

    receiving_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    receiving_order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gross_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    net_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    deductions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    anomaly_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class WeightStandardCreate(_BaseSchema):
    """创建扣秤标准（草稿态 — approved_by 为 NULL）"""

    deduct_type: DeductType
    deduct_method: DeductMethod
    deduct_value: Decimal = Field(ge=0, description="百分比模式: %值; 固定模式: kg")
    tolerance_pct: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    effective_from: date
    effective_to: Optional[date] = None
    notes: Optional[str] = None


class WeightStandardUpdate(_BaseSchema):
    """更新扣秤标准（仅未审批草稿可更新）"""

    deduct_type: Optional[DeductType] = None
    deduct_method: Optional[DeductMethod] = None
    deduct_value: Optional[Decimal] = Field(default=None, ge=0)
    tolerance_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    notes: Optional[str] = None


class WeightStandardRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    ingredient_id: uuid.UUID
    deduct_type: str
    deduct_method: str
    deduct_value: Decimal
    tolerance_pct: Decimal
    effective_from: date
    effective_to: Optional[date]
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


class CalcNetWeightRequest(_BaseSchema):
    """手动触发净重计算（收货员用）"""

    ingredient_id: str
    gross_weight_kg: Decimal = Field(gt=0)


class CalcNetWeightResponse(_BaseSchema):
    gross_weight_kg: Decimal
    net_weight_kg: Decimal
    deductions: list[dict]
    anomaly_detected: bool
