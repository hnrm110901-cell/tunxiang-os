"""宴会排产引擎 ORM模型"""

import uuid
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Boolean, Date, Index, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetProductionPlan(TenantBase):
    """宴会排产主计划"""

    __tablename__ = "banquet_production_plans"

    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    total_dishes: Mapped[int] = mapped_column(Integer, default=0)
    total_servings: Mapped[int] = mapped_column(Integer, default=0, comment="总份数=菜品数×桌数")
    prep_start_time: Mapped[Optional[time]] = mapped_column(Time)
    service_start_time: Mapped[Optional[time]] = mapped_column(Time)
    course_timeline_json: Mapped[dict] = mapped_column(JSON, default=list, comment="出菜时序")
    staff_required_json: Mapped[dict] = mapped_column(JSON, default=dict, comment="人员需求")
    kitchen_notes: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column()

    __table_args__ = (
        Index("idx_bpp_banquet", "tenant_id", "banquet_id"),
        Index("idx_bpp_store_date", "tenant_id", "store_id", "plan_date"),
        {"comment": "宴会排产主计划"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "banquet_id": str(self.banquet_id),
            "store_id": str(self.store_id),
            "plan_date": self.plan_date.isoformat() if self.plan_date else None,
            "status": self.status,
            "total_dishes": self.total_dishes,
            "total_servings": self.total_servings,
            "prep_start_time": self.prep_start_time.isoformat() if self.prep_start_time else None,
            "service_start_time": self.service_start_time.isoformat() if self.service_start_time else None,
            "course_timeline_json": self.course_timeline_json,
            "staff_required_json": self.staff_required_json,
            "kitchen_notes": self.kitchen_notes,
            "confirmed_by": str(self.confirmed_by) if self.confirmed_by else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BanquetProductionTask(TenantBase):
    """宴会排产任务"""

    __tablename__ = "banquet_production_tasks"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    course_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="出菜序号")
    course_name: Mapped[Optional[str]] = mapped_column(String(50), comment="凉菜/热菜/主食/汤/甜品")
    dish_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    dish_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="份数=桌数")
    prep_time_min: Mapped[int] = mapped_column(Integer, default=0)
    cook_time_min: Mapped[int] = mapped_column(Integer, default=0)
    station_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    station_name: Mapped[Optional[str]] = mapped_column(String(50))
    assigned_chef_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    assigned_chef_name: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    target_serve_time: Mapped[Optional[time]] = mapped_column(Time)
    started_at: Mapped[Optional[datetime]] = mapped_column()
    completed_at: Mapped[Optional[datetime]] = mapped_column()
    notes: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        Index("idx_bpt_plan", "tenant_id", "plan_id"),
        Index("idx_bpt_status", "tenant_id", "status"),
        {"comment": "宴会排产任务"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "plan_id": str(self.plan_id),
            "course_no": self.course_no,
            "course_name": self.course_name,
            "dish_id": str(self.dish_id) if self.dish_id else None,
            "dish_name": self.dish_name,
            "quantity": self.quantity,
            "prep_time_min": self.prep_time_min,
            "cook_time_min": self.cook_time_min,
            "station_id": str(self.station_id) if self.station_id else None,
            "station_name": self.station_name,
            "assigned_chef_id": str(self.assigned_chef_id) if self.assigned_chef_id else None,
            "assigned_chef_name": self.assigned_chef_name,
            "status": self.status,
            "target_serve_time": self.target_serve_time.isoformat() if self.target_serve_time else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
