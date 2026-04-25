"""预订配置模型 — 包间/区域配置 + 时段配置

将硬编码的 _DEFAULT_ROOM_CONFIG 和 _DEFAULT_TIME_SLOTS 改为数据库驱动。
"""

import uuid
from datetime import time

from sqlalchemy import Boolean, Index, Integer, BigInteger, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ReservationConfig(TenantBase):
    """包间/区域配置"""

    __tablename__ = "reservation_configs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    room_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="包间编码，门店内唯一",
    )
    room_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="包间名称",
    )
    room_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="private",
        comment="private|hall|outdoor",
    )
    min_guests: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_guests: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    deposit_fen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="定金(分)")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("uq_reservation_config_store_room", "store_id", "room_code", unique=True),
        {"comment": "预订包间/区域配置"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "room_code": self.room_code,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "min_guests": self.min_guests,
            "max_guests": self.max_guests,
            "deposit_fen": self.deposit_fen,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReservationTimeSlot(TenantBase):
    """预订时段配置"""

    __tablename__ = "reservation_time_slots"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    slot_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="时段名称",
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False, comment="开始时间")
    end_time: Mapped[time] = mapped_column(Time, nullable=False, comment="结束时间")
    dining_duration_min: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
        comment="默认用餐时长(分钟)",
    )
    max_reservations: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="最大预订数,0=不限",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        {"comment": "预订时段配置"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "slot_name": self.slot_name,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "dining_duration_min": self.dining_duration_min,
            "max_reservations": self.max_reservations,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
