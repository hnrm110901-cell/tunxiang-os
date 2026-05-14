"""RFQ 询价单 ORM + Pydantic Schema（PRD-04 sub-A / Phase 2 W9 / T2 infra）

ORM（SQLAlchemy 2.0 typed Mapped[]）:
  RFQ             — 询价单主表
  RFQItem         — 询价单明细行
  RFQInvitee      — 供应商邀请记录
  RFQQuote        — 供应商报价
  RFQAward        — 中标记录（Tier 1 资金路径前置 — sub-B award 写入）

Pydantic V2 Schema:
  RFQ Create / Update / Read + 5 表各 Read 模型

枚举:
  RFQStatus — draft / published / quoting / comparing / awarded / cancelled

Sub-A 范围：schema-only — 不含 service / route / UI / 业务逻辑（sub-B 落 award + 二级审批
+ #579 200 桌并发；sub-C 落前端比价表 + AI 推荐 UI）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
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
# 枚举（与 v431 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────────────────────


class RFQStatus(str, Enum):
    """询价单状态机：

    draft → published → quoting → comparing → awarded / cancelled

    业务流程：
    - draft: 采购员创建草稿
    - published: 邀请已发送，等供应商响应
    - quoting: 至少 1 家供应商已报价
    - comparing: 截止后，正在审核比价表
    - awarded: 已中标（rfq_awards 写入，进采购单生成）
    - cancelled: 终止（任何阶段均可，含审计 reason）
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    QUOTING = "quoting"
    COMPARING = "comparing"
    AWARDED = "awarded"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class RFQ(TenantBase):
    """询价单主表（rfqs）"""

    __tablename__ = "rfqs"

    rfq_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    initiator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RFQStatus.DRAFT.value
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class RFQItem(TenantBase):
    """询价单明细行（rfq_items）— 一询价单可含多 SKU"""

    __tablename__ = "rfq_items"

    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    qty_required: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    qty_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    spec_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RFQInvitee(TenantBase):
    """供应商邀请记录（rfq_invitees）— UNIQUE(rfq_id, supplier_id) 防重邀"""

    __tablename__ = "rfq_invitees"

    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RFQQuote(TenantBase):
    """供应商报价（rfq_quotes）— UNIQUE(rfq_id, supplier_id, ingredient_id)"""

    __tablename__ = "rfq_quotes"

    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 金额字段单位：分（整数）— 与 invoice/wine_storage Tier 1 资金路径一致
    unit_price_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    qty_offered: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 4), nullable=True
    )
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RFQAward(TenantBase):
    """中标记录（rfq_awards）— Tier 1 资金路径前置，UNIQUE(rfq_id) 一单一中标

    ai_recommendation_followed: ⭐ RLHF 训练信号 — 长期 AI 自动议价的核心数据资产
    """

    __tablename__ = "rfq_awards"

    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selected_quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ai_recommendation_followed: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ── RFQ ────────────────────────────────────────────────────────────────────


class RFQItemCreate(_BaseSchema):
    """RFQ 明细行（创建 RFQ 时嵌入 items 列表）"""

    ingredient_id: str
    qty_required: Decimal = Field(gt=0)
    qty_unit: Optional[str] = None
    spec_notes: Optional[str] = None


class RFQCreate(_BaseSchema):
    """创建询价单（草稿态）"""

    deadline: datetime
    notes: Optional[str] = None
    items: list[RFQItemCreate] = Field(default_factory=list, min_length=1)
    invited_supplier_ids: list[str] = Field(default_factory=list)


class RFQUpdate(_BaseSchema):
    """更新询价单（仅 draft 状态可改 — sub-B service 层强制）"""

    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[RFQStatus] = None


class RFQRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    rfq_number: Optional[str]
    initiator_id: uuid.UUID
    deadline: datetime
    status: str
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class RFQItemRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    rfq_id: uuid.UUID
    ingredient_id: uuid.UUID
    qty_required: Decimal
    qty_unit: Optional[str]
    spec_notes: Optional[str]
    created_at: datetime


class RFQInviteeRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    rfq_id: uuid.UUID
    supplier_id: uuid.UUID
    invited_at: datetime
    responded_at: Optional[datetime]


class RFQQuoteCreate(_BaseSchema):
    """供应商报价（供应商门户提交）"""

    rfq_id: str
    ingredient_id: str
    unit_price_fen: int = Field(gt=0, description="单价（分）— 整数")
    qty_offered: Optional[Decimal] = Field(default=None, gt=0)
    valid_until: Optional[date] = None
    notes: Optional[str] = None


class RFQQuoteRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    rfq_id: uuid.UUID
    supplier_id: uuid.UUID
    ingredient_id: uuid.UUID
    unit_price_fen: int
    qty_offered: Optional[Decimal]
    valid_until: Optional[date]
    notes: Optional[str]
    submitted_at: datetime


class RFQAwardCreate(_BaseSchema):
    """中标记录（sub-B Tier 1 award 路径写入）"""

    selected_quote_id: str
    reason: str = Field(min_length=1, description="合规审计 — 选 A 不选 B 的理由")
    ai_recommendation_followed: Optional[bool] = Field(
        default=None, description="是否采纳 AI 推荐（RLHF 训练信号）"
    )


class RFQAwardRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    rfq_id: uuid.UUID
    selected_quote_id: uuid.UUID
    reason: str
    ai_recommendation_followed: Optional[bool]
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    created_by: uuid.UUID
    created_at: datetime
