"""
采购付款 ORM 模型
包含：ProcurementPayment（付款单主表）、ProcurementPaymentItem（付款条目）、
     ProcurementReconciliation（对账记录）

设计说明：
- 与 tx-supply 采购订单通过 purchase_order_id 关联（跨服务外键，不设 DB 级 FK）
- 幂等保护：(tenant_id, purchase_order_id) 唯一键，防止重复创建
- 所有金额字段单位为分(fen)，整数存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离（tenant_id + is_deleted 由基类提供）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import NUMERIC, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# ProcurementPayment — 采购付款单主表
# ─────────────────────────────────────────────────────────────────────────────


class ProcurementPayment(TenantBase):
    """
    采购付款单
    由采购订单审批通过后自动生成（事件驱动），也支持手工创建。
    (tenant_id, purchase_order_id) 唯一，防止重复付款单。
    """

    __tablename__ = "procurement_payments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "purchase_order_id",
            name="uq_procurement_payments_tenant_purchase_order",
        ),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="tx-supply 采购订单ID（唯一键，幂等保护）"
    )
    purchase_order_no: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="采购单号（冗余存储，避免跨服务查询）"
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="供应商ID"
    )
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="供应商名称（冗余存储）")
    payment_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="purchase", comment="付款类型：purchase / deposit / final"
    )
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="总金额，单位：分(fen)")
    paid_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="已付金额，单位：分(fen)")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True, comment="状态：pending / approved / paid / cancelled"
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="付款到期日")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="创建人员工ID")

    # 关系
    items: Mapped[List["ProcurementPaymentItem"]] = relationship(
        "ProcurementPaymentItem",
        back_populates="payment",
        cascade="all, delete-orphan",
        lazy="select",
    )
    reconciliations: Mapped[List["ProcurementReconciliation"]] = relationship(
        "ProcurementReconciliation",
        back_populates="payment",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ProcurementPaymentItem — 付款条目（与采购订单行对应）
# ─────────────────────────────────────────────────────────────────────────────


class ProcurementPaymentItem(TenantBase):
    """
    付款条目
    对应采购订单行（order_item_id），记录每个商品的数量、单价、金额。
    invoice_id 在发票匹配后填充。
    """

    __tablename__ = "procurement_payment_items"

    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("procurement_payments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属付款单ID",
    )
    order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="tx-supply 采购行ID"
    )
    product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="商品名称（冗余存储）")
    quantity: Mapped[Optional[float]] = mapped_column(NUMERIC(12, 3), nullable=True, comment="数量")
    unit_price: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="单价，单位：分(fen)")
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="金额，单位：分(fen)")
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="关联发票ID（发票匹配后填充）"
    )

    # 关系
    payment: Mapped[Optional["ProcurementPayment"]] = relationship(
        "ProcurementPayment", back_populates="items", foreign_keys=[payment_id]
    )


# ─────────────────────────────────────────────────────────────────────────────
# ProcurementReconciliation — 对账记录
# ─────────────────────────────────────────────────────────────────────────────


class ProcurementReconciliation(TenantBase):
    """
    对账记录
    比较付款单金额与实际发票总金额，记录差异。
    discrepancy_amount = payment_amount - invoice_amount（正值=多付，负值=少付）
    """

    __tablename__ = "procurement_reconciliations"

    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_payments.id"), nullable=True, index=True, comment="所属付款单ID"
    )
    reconciled_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="对账操作人员工ID"
    )
    reconciliation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
        comment="对账状态：pending / matched / discrepancy / resolved",
    )
    payment_amount: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, comment="付款单金额，单位：分(fen)"
    )
    invoice_amount: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, comment="发票总金额，单位：分(fen)"
    )
    discrepancy_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="差异金额（payment_amount - invoice_amount），单位：分(fen)"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="对账完成时间"
    )

    # 关系
    payment: Mapped[Optional["ProcurementPayment"]] = relationship(
        "ProcurementPayment", back_populates="reconciliations", foreign_keys=[payment_id]
    )
