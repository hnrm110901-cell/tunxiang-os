"""宴会场地与预订 ORM模型 — Phase 1"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetVenue(TenantBase):
    """宴会场地/厅"""

    __tablename__ = "banquet_venues"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    venue_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="grand_hall/medium_hall/private_room/outdoor/rooftop/multi_function",
    )
    floor: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="楼层",
    )
    area_sqm: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="面积(平方米)",
    )
    max_table_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="最大桌数",
    )
    min_table_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="最少桌数",
    )
    max_guest_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="最大容纳人数",
    )
    has_stage: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否有舞台")
    has_led_screen: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否有LED屏")
    has_sound_system: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否有音响")
    has_projector: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否有投影")
    venue_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="场地费(分)，0=免费",
    )
    decoration_options: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="布置方案选项",
    )
    photos: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="场地照片URL列表",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_bv_tenant_store", "tenant_id", "store_id"),
        Index("idx_bv_type", "tenant_id", "venue_type"),
        {"comment": "宴会场地/厅"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "name": self.name,
            "venue_type": self.venue_type,
            "floor": self.floor,
            "area_sqm": self.area_sqm,
            "max_table_count": self.max_table_count,
            "min_table_count": self.min_table_count,
            "max_guest_count": self.max_guest_count,
            "has_stage": self.has_stage,
            "has_led_screen": self.has_led_screen,
            "has_sound_system": self.has_sound_system,
            "has_projector": self.has_projector,
            "venue_fee_fen": self.venue_fee_fen,
            "decoration_options": self.decoration_options,
            "photos": self.photos,
            "description": self.description,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetVenueBooking(TenantBase):
    """宴会场地预订"""

    __tablename__ = "banquet_venue_bookings"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    banquet_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联宴会订单ID",
    )
    booking_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="预订日期",
    )
    time_slot: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="lunch",
        comment="lunch/dinner/full_day",
    )
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_count_est: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="held",
        index=True,
        comment="held/confirmed/released/completed/cancelled",
    )
    held_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="预留到期时间",
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_bvb_venue_date", "tenant_id", "venue_id", "booking_date"),
        Index("idx_bvb_store_date", "tenant_id", "store_id", "booking_date"),
        Index("idx_bvb_status", "tenant_id", "status"),
        {"comment": "宴会场地预订"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "venue_id": str(self.venue_id),
            "store_id": str(self.store_id),
            "lead_id": str(self.lead_id) if self.lead_id else None,
            "banquet_id": str(self.banquet_id) if self.banquet_id else None,
            "booking_date": self.booking_date.isoformat() if self.booking_date else None,
            "time_slot": self.time_slot,
            "table_count": self.table_count,
            "guest_count_est": self.guest_count_est,
            "customer_name": self.customer_name,
            "phone": self.phone,
            "event_type": self.event_type,
            "status": self.status,
            "held_until": self.held_until.isoformat() if self.held_until else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "cancel_reason": self.cancel_reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }
