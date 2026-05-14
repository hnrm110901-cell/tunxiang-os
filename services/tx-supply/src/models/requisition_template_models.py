"""申购模板 ORM + Pydantic Schema（PRD-07 / Phase 2 W10 / T2）

ORM（SQLAlchemy 2.0 typed Mapped[]）:
  RequisitionTemplate                   — 模板主表 (按品类)
  RequisitionTemplateItem               — 模板明细 (template_id FK CASCADE)
  WarehouseRequisitionTemplateBinding   — 仓库绑定 (warehouse_id + template_id)

Pydantic V2 Schema:
  TemplateCreate / Update / Read + Item Create / Read + Binding Create / Read +
  GenerateFromTemplateRequest / GeneratedRequisitionDraft（一键发起申购返回）

枚举：
  TemplateCategory  — seafood / meat / vegetable / seasoning / beverage / dry_goods / frozen / other
  QtyMethod         — fixed / ai_predicted / last_order / par_level

业务流：
  总部建模板 → 仓库绑定模板 → 门店选模板 → 一键生成申购单草稿（AI 推荐量填充 NULL 字段）→
  店长走 existing 申购审批流（services/tx-supply/src/services/requisition.py）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# 枚举（与 v432 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────────────────────


class TemplateCategory(str, Enum):
    SEAFOOD = "seafood"
    MEAT = "meat"
    VEGETABLE = "vegetable"
    SEASONING = "seasoning"
    BEVERAGE = "beverage"
    DRY_GOODS = "dry_goods"
    FROZEN = "frozen"
    OTHER = "other"


class QtyMethod(str, Enum):
    """模板项数量计算方法：
    - fixed:        固定数量（default_qty 必填）
    - ai_predicted: AI 推荐（一键发起时调 smart_replenishment 引擎）
    - last_order:   上次申购量（一键发起时查近一次 approved 申购）
    - par_level:    库存补齐量（一键发起时查 inventory_thresholds.target_stock - current）
    """

    FIXED = "fixed"
    AI_PREDICTED = "ai_predicted"
    LAST_ORDER = "last_order"
    PAR_LEVEL = "par_level"


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class RequisitionTemplate(TenantBase):
    """申购模板主表（requisition_templates）"""

    __tablename__ = "requisition_templates"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class RequisitionTemplateItem(TenantBase):
    """申购模板明细（requisition_template_items）— UNIQUE(template_id, ingredient_id)"""

    __tablename__ = "requisition_template_items"

    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    default_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    qty_method: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
    qty_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class WarehouseRequisitionTemplateBinding(TenantBase):
    """仓库 → 模板绑定（warehouse_requisition_template_bindings）

    一个仓库可绑定多个模板（按 priority 排序）。每行 UNIQUE(warehouse_id, template_id)。
    auto_trigger_cron NULL = 手动触发；非 NULL = cron 表达式（如 '0 6 * * *' 每天 6 点）。
    """

    __tablename__ = "warehouse_requisition_template_bindings"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    auto_trigger_cron: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ── 模板主表 ────────────────────────────────────────────────────────────────


class TemplateItemCreate(_BaseSchema):
    """模板明细行（创建模板时嵌入 items 列表）"""

    ingredient_id: uuid.UUID
    default_qty: Optional[Decimal] = Field(default=None, gt=0)
    qty_method: QtyMethod = QtyMethod.FIXED
    qty_unit: Optional[str] = Field(default=None, max_length=16)
    sort_order: int = Field(default=0, ge=0)
    notes: Optional[str] = Field(default=None, max_length=500)


class TemplateCreate(_BaseSchema):
    """创建模板（含明细 items 同事务原子写）"""

    name: str = Field(min_length=1, max_length=120)
    category: TemplateCategory
    notes: Optional[str] = Field(default=None, max_length=500)
    items: list[TemplateItemCreate] = Field(default_factory=list, min_length=1)


class TemplateUpdate(_BaseSchema):
    """更新模板（不改 items, items 走单独 endpoint）"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[TemplateCategory] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class TemplateRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    category: str
    is_active: bool
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class TemplateItemRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    template_id: uuid.UUID
    ingredient_id: uuid.UUID
    default_qty: Optional[Decimal]
    qty_method: str
    qty_unit: Optional[str]
    sort_order: int
    notes: Optional[str]


# ── 仓库绑定 ────────────────────────────────────────────────────────────────


class BindingCreate(_BaseSchema):
    warehouse_id: uuid.UUID
    template_id: uuid.UUID
    auto_trigger_cron: Optional[str] = Field(default=None, max_length=64)
    priority: int = Field(default=0, ge=0)


class BindingRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    warehouse_id: uuid.UUID
    template_id: uuid.UUID
    auto_trigger_cron: Optional[str]
    priority: int
    created_by: uuid.UUID
    created_at: datetime


# ── 一键发起申购 ────────────────────────────────────────────────────────────


class GenerateFromTemplateRequest(_BaseSchema):
    """一键发起申购请求（基于模板 + 仓库/门店 → 草稿）

    AI 推荐量 (qty_method='ai_predicted') 调 SmartReplenishmentService.check_and_recommend
    需要 store_id；不传则跳过 AI 推荐（item 数量留 NULL，前端提示用户填）。
    """

    store_id: Optional[uuid.UUID] = Field(
        default=None, description="门店 ID — qty_method=ai_predicted/par_level 需要"
    )
    notes: Optional[str] = Field(default=None, max_length=500)


class GeneratedRequisitionItem(_BaseSchema):
    """一键生成的申购明细（前端预览，未入库）"""

    ingredient_id: uuid.UUID
    suggested_qty: Optional[Decimal]
    qty_method: str
    qty_unit: Optional[str]
    qty_source: str = Field(description="数量来源说明: 模板默认 / AI 推荐 / 上次申购 / 库存补齐 / 未填")
    notes: Optional[str]


class GeneratedRequisitionDraft(_BaseSchema):
    """一键生成的申购单草稿（前端 review 后调 existing /requisitions endpoint 入库）"""

    template_id: uuid.UUID
    template_name: str
    store_id: Optional[uuid.UUID]
    items: list[GeneratedRequisitionItem]
    notes: Optional[str]
