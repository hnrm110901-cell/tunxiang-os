"""宴会结算 ORM模型"""
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.ontology.src.base import TenantBase

class BanquetSettlement(TenantBase):
    __tablename__ = "banquet_settlements"
    settlement_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="BST-XXXXXXXXXXXX")
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contract_amount_fen: Mapped[int] = mapped_column(Integer, default=0)
    deposit_paid_fen: Mapped[int] = mapped_column(Integer, default=0)
    live_order_amount_fen: Mapped[int] = mapped_column(Integer, default=0)
    service_fee_fen: Mapped[int] = mapped_column(Integer, default=0)
    venue_fee_fen: Mapped[int] = mapped_column(Integer, default=0)
    decoration_fee_fen: Mapped[int] = mapped_column(Integer, default=0)
    other_fee_fen: Mapped[int] = mapped_column(Integer, default=0)
    discount_fen: Mapped[int] = mapped_column(Integer, default=0)
    subtotal_fen: Mapped[int] = mapped_column(Integer, default=0)
    balance_due_fen: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[Optional[str]] = mapped_column(String(30))
    payment_ref: Mapped[Optional[str]] = mapped_column(String(100))
    settled_at: Mapped[Optional[datetime]] = mapped_column()
    settled_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    invoice_status: Mapped[str] = mapped_column(String(20), default="none")
    invoice_no: Mapped[Optional[str]] = mapped_column(String(50))
    invoice_amount_fen: Mapped[int] = mapped_column(Integer, default=0)
    b2b_client_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    b2b_monthly: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (Index("idx_bs_banquet", "tenant_id", "banquet_id"), Index("idx_bs_store", "tenant_id", "store_id"), {"comment": "宴会结算"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "settlement_no": self.settlement_no, "banquet_id": str(self.banquet_id), "contract_amount_fen": self.contract_amount_fen, "deposit_paid_fen": self.deposit_paid_fen, "live_order_amount_fen": self.live_order_amount_fen, "subtotal_fen": self.subtotal_fen, "balance_due_fen": self.balance_due_fen, "payment_method": self.payment_method, "invoice_status": self.invoice_status, "b2b_monthly": self.b2b_monthly, "settled_at": self.settled_at.isoformat() if self.settled_at else None}

class BanquetSettlementItem(TenantBase):
    __tablename__ = "banquet_settlement_items"
    settlement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_fen: Mapped[int] = mapped_column(Integer, default=0)
    subtotal_fen: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(30), default="contract")
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (Index("idx_bsi_settlement", "tenant_id", "settlement_id"), {"comment": "结算明细"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "settlement_id": str(self.settlement_id), "item_type": self.item_type, "item_name": self.item_name, "quantity": self.quantity, "unit_price_fen": self.unit_price_fen, "subtotal_fen": self.subtotal_fen, "source": self.source}
