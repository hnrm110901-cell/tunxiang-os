"""宴会日调度 ORM模型"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetDaySchedule(TenantBase):
    """当日宴会总调度"""

    __tablename__ = "banquet_day_schedules"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False)
    banquet_ids: Mapped[dict] = mapped_column(JSON, default=list)
    banquet_count: Mapped[int] = mapped_column(Integer, default=0)
    total_guests: Mapped[int] = mapped_column(Integer, default=0)
    total_tables: Mapped[int] = mapped_column(Integer, default=0)
    venue_allocation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    staff_allocation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline_json: Mapped[dict] = mapped_column(JSON, default=list, comment="统一时间轴")
    kitchen_load_json: Mapped[dict] = mapped_column(JSON, default=dict, comment="厨房负载")
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_bds_store_date", "tenant_id", "store_id", "schedule_date"),
        Index("idx_bds_status", "tenant_id", "status"),
        {"comment": "当日宴会总调度"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "store_id": str(self.store_id),
            "schedule_date": self.schedule_date.isoformat() if self.schedule_date else None,
            "banquet_ids": self.banquet_ids,
            "banquet_count": self.banquet_count,
            "total_guests": self.total_guests,
            "total_tables": self.total_tables,
            "venue_allocation_json": self.venue_allocation_json,
            "staff_allocation_json": self.staff_allocation_json,
            "timeline_json": self.timeline_json,
            "kitchen_load_json": self.kitchen_load_json,
            "status": self.status,
            "confirmed_by": str(self.confirmed_by) if self.confirmed_by else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
