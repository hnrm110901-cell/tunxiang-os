"""支付模型 — 多支付方式 + 退款"""
import uuid

from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase
from .enums import PaymentMethod, PaymentStatus, RefundType


class Payment(TenantBase):
    """支付记录 — 一笔订单可有多条支付（混合支付）"""
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    payment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="支付流水号")
    method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentMethod.cash.value
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="支付金额(分)")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.pending.value, index=True
    )

    # 第三方支付信息
    trade_no: Mapped[str | None] = mapped_column(String(128), comment="第三方交易号(微信/支付宝)")
    paid_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    # 挂账信息
    credit_account_name: Mapped[str | None] = mapped_column(String(100), comment="挂账单位/人")
    credit_account_phone: Mapped[str | None] = mapped_column(String(20))

    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)


class Refund(TenantBase):
    """退款记录"""
    __tablename__ = "refunds"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    refund_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    refund_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RefundType.full.value
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="退款金额(分)")
    reason: Mapped[str | None] = mapped_column(String(500))
    operator_id: Mapped[str | None] = mapped_column(String(50), comment="操作员ID")
    refunded_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    trade_no: Mapped[str | None] = mapped_column(String(128), comment="第三方退款交易号")
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)
