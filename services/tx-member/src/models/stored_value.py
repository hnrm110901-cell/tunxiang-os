"""储值卡模型 — 预付费/充值/消费/退款/赠送金

金额单位：分（fen）
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class StoredValueCard(TenantBase):
    """储值卡"""
    __tablename__ = "stored_value_cards"

    card_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True,
    )
    card_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="personal",
        comment="personal/corporate/gift",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active",
        comment="active/frozen/expired/cancelled",
    )
    balance_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="本金余额(分)")
    gift_balance_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="赠送金余额(分)")
    total_recharged_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计充值(分)")
    total_consumed_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计消费(分)")
    total_refunded_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计退款(分)")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="开卡门店")
    operator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="开卡操作员")
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("idx_sv_card_customer", "customer_id", "status"),
        {"comment": "储值卡"},
    )


class StoredValueTransaction(TenantBase):
    """储值卡交易流水"""
    __tablename__ = "stored_value_transactions"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stored_value_cards.id"), nullable=False, index=True,
    )
    txn_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="recharge/consume/refund/gift_grant/transfer_in/transfer_out/freeze/unfreeze",
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="交易金额(分)")
    gift_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="赠送金变动(分)")
    balance_after_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="交易后本金余额(分)")
    gift_balance_after_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="交易后赠送金余额(分)")
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="关联订单ID")
    operator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="操作员ID")
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="交易门店")
    remark: Mapped[str | None] = mapped_column(String(255))
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("idx_sv_txn_card_time", "card_id", "created_at"),
        {"comment": "储值卡交易流水"},
    )


class RechargeRule(TenantBase):
    """充值赠送规则（充500送50）"""
    __tablename__ = "recharge_rules"

    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    recharge_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="充值金额(分)")
    gift_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="赠送金额(分)")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    store_ids: Mapped[list | None] = mapped_column(JSON, comment="适用门店，null=全部")

    __table_args__ = ({"comment": "充值赠送规则"},)
