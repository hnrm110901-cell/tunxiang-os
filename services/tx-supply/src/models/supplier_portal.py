"""供应商门户 ORM 模型

表：
  supplier_accounts        — 供应商账户（基本信息 + 评分）
  supplier_quotations      — 供应商报价（RFQ 询价 + 报价记录）
  supplier_reconciliations — 对账记录（合同 + 交付 + 价格历史）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class SupplierAccount(TenantBase):
    """供应商账户"""

    __tablename__ = "supplier_accounts"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="seafood/meat/vegetable/seasoning/frozen/dry_goods/beverage/other",
    )
    contact: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment='{"person":"张三","phone":"138xxx","address":"长沙市xxx"}',
    )
    certifications: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment='["食品经营许可证","ISO22000"]',
    )
    payment_terms: Mapped[str] = mapped_column(
        String(30), nullable=False, default="net30", comment="net30/net60/cod",
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active",
        comment="active/inactive/suspended/blacklisted",
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # relationships
    quotations: Mapped[list[SupplierQuotation]] = relationship(
        back_populates="supplier", lazy="selectin",
    )
    reconciliations: Mapped[list[SupplierReconciliation]] = relationship(
        back_populates="supplier", lazy="selectin",
    )


class SupplierQuotation(TenantBase):
    """供应商报价（RFQ 询价 + 报价）"""

    __tablename__ = "supplier_quotations"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_accounts.id"),
        nullable=False,
    )
    rfq_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="询价单号",
    )
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_price_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_price_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="open",
        comment="open/quoted/accepted/rejected/expired",
    )
    composite_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_detail: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment='{"price_score":80,"delivery_score":90,"reliability_score":75}',
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # relationship
    supplier: Mapped[SupplierAccount] = relationship(
        back_populates="quotations", lazy="selectin",
    )


class SupplierReconciliation(TenantBase):
    """对账记录（合同执行 + 交付 + 价格）"""

    __tablename__ = "supplier_reconciliations"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_accounts.id"),
        nullable=False,
    )
    record_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="contract/delivery/price_history/store_link",
    )
    reference_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="关联的合同ID/订单ID等",
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    ingredient_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    # 交付相关
    on_time: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_result: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="pass/fail",
    )
    price_adherence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    price_competitiveness: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 价格相关
    price_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 合同相关
    contract_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="合同详情：items/start_date/end_date/penalties 等",
    )
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
