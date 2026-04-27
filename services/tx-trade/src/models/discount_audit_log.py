import uuid
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DiscountAuditLog(TenantBase):
    """折扣审计链记录

    每笔折扣/赠品/退菜操作均写入此表，不可修改，仅软删除。
    action_type 枚举: discount_pct / discount_amt / gift_item /
                      return_item / free_order / price_override / coupon
    """

    __tablename__ = "discount_audit_log"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True, comment="门店ID")
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True, comment="订单ID")
    order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="行级折扣时关联的订单明细ID"
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="操作员ID")
    operator_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="操作员姓名（快照）")

    approver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="授权人ID（与operator不同时有值）"
    )
    approver_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="授权人姓名（快照）")

    action_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="操作类型: discount_pct/discount_amt/gift_item/return_item/free_order/price_override/coupon",
    )

    original_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="原始金额")
    final_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="折后金额")
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, comment="折扣金额 = original_amount - final_amount"
    )

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="折扣原因")
    extra: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="额外上下文（如优惠券ID、活动ID）"
    )
    device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="操作设备ID")

    __table_args__ = (
        Index("ix_dal_tenant_store", "tenant_id", "store_id"),
        Index("ix_dal_operator", "operator_id", "created_at"),
    )
