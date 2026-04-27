"""宴会现场管理 ORM模型"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetLiveOrder(TenantBase):
    __tablename__ = "banquet_live_orders"
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="add_dish/add_drink/special_request/cancel_dish/upgrade_dish/extra_service"
    )
    items_json: Mapped[dict] = mapped_column(JSON, default=list)
    amount_fen: Mapped[int] = mapped_column(Integer, default=0, comment="金额(分)")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    requested_name: Mapped[Optional[str]] = mapped_column(String(100))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    reject_reason: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column()
    notes: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (Index("idx_blo_banquet", "tenant_id", "banquet_id"), {"comment": "宴会现场订单"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "banquet_id": str(self.banquet_id),
            "order_type": self.order_type,
            "items_json": self.items_json,
            "amount_fen": self.amount_fen,
            "quantity": self.quantity,
            "requested_name": self.requested_name,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BanquetGuestCheckIn(TenantBase):
    __tablename__ = "banquet_guest_check_ins"
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    table_no: Mapped[Optional[str]] = mapped_column(String(20))
    guest_name: Mapped[Optional[str]] = mapped_column(String(100))
    guest_phone: Mapped[Optional[str]] = mapped_column(String(20))
    check_in_time: Mapped[datetime] = mapped_column()
    vip_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_notes: Mapped[Optional[str]] = mapped_column(String(500))
    seat_assignment: Mapped[Optional[str]] = mapped_column(String(50))
    __table_args__ = (Index("idx_bgci_banquet", "tenant_id", "banquet_id"), {"comment": "宾客签到"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "banquet_id": str(self.banquet_id),
            "table_no": self.table_no,
            "guest_name": self.guest_name,
            "check_in_time": self.check_in_time.isoformat() if self.check_in_time else None,
            "vip_flag": self.vip_flag,
            "dietary_notes": self.dietary_notes,
            "seat_assignment": self.seat_assignment,
        }
