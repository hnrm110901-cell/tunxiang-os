"""厨房产能 + 冲突管理 ORM模型"""

import uuid
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Boolean, Date, Index, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class KitchenCapacitySlot(TenantBase):
    """厨房产能时段"""

    __tablename__ = "kitchen_capacity_slots"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    max_dishes_per_hour: Mapped[int] = mapped_column(Integer, default=100)
    max_concurrent_banquets: Mapped[int] = mapped_column(Integer, default=2)
    current_load_dishes: Mapped[int] = mapped_column(Integer, default=0)
    current_banquet_count: Mapped[int] = mapped_column(Integer, default=0)
    available_capacity_dishes: Mapped[int] = mapped_column(Integer, default=100)
    staff_on_duty_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[Optional[str]] = mapped_column(String(200))

    __table_args__ = (
        Index("idx_kcs_store_date", "tenant_id", "store_id", "slot_date"),
        {"comment": "厨房产能时段"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "store_id": str(self.store_id),
            "slot_date": self.slot_date.isoformat() if self.slot_date else None,
            "time_slot": self.time_slot,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "max_dishes_per_hour": self.max_dishes_per_hour,
            "max_concurrent_banquets": self.max_concurrent_banquets,
            "current_load_dishes": self.current_load_dishes,
            "current_banquet_count": self.current_banquet_count,
            "available_capacity_dishes": self.available_capacity_dishes,
            "staff_on_duty_json": self.staff_on_duty_json,
            "is_blocked": self.is_blocked,
            "block_reason": self.block_reason,
        }


class BanquetCapacityConflict(TenantBase):
    """产能冲突记录"""

    __tablename__ = "banquet_capacity_conflicts"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conflict_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[str] = mapped_column(String(20), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, comment="info/warning/critical")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_banquet_ids: Mapped[dict] = mapped_column(JSON, default=list)
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)

    __table_args__ = (
        Index("idx_bcc_store_date", "tenant_id", "store_id", "conflict_date"),
        Index("idx_bcc_status", "tenant_id", "status"),
        {"comment": "产能冲突记录"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "store_id": str(self.store_id),
            "conflict_date": self.conflict_date.isoformat() if self.conflict_date else None,
            "time_slot": self.time_slot,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "description": self.description,
            "affected_banquet_ids": self.affected_banquet_ids,
            "resolution": self.resolution,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
