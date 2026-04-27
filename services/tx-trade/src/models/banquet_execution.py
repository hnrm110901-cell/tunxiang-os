"""宴会执行SOP ORM模型"""

import uuid
from datetime import datetime, time
from typing import Optional

from sqlalchemy import Index, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetExecutionPlan(TenantBase):
    __tablename__ = "banquet_execution_plans"
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sop_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    checkpoints_json: Mapped[dict] = mapped_column(JSON, default=list)
    assigned_staff_json: Mapped[dict] = mapped_column(JSON, default=dict)
    total_checkpoints: Mapped[int] = mapped_column(Integer, default=0)
    completed_checkpoints: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    started_at: Mapped[Optional[datetime]] = mapped_column()
    completed_at: Mapped[Optional[datetime]] = mapped_column()
    __table_args__ = (Index("idx_bep_banquet", "tenant_id", "banquet_id"), {"comment": "宴会执行计划"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "banquet_id": str(self.banquet_id),
            "store_id": str(self.store_id),
            "checkpoints_json": self.checkpoints_json,
            "total_checkpoints": self.total_checkpoints,
            "completed_checkpoints": self.completed_checkpoints,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BanquetExecutionLog(TenantBase):
    __tablename__ = "banquet_execution_logs"
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    checkpoint_index: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_name: Mapped[str] = mapped_column(String(100), nullable=False)
    checkpoint_type: Mapped[str] = mapped_column(String(30), default="task")
    scheduled_time: Mapped[Optional[time]] = mapped_column(Time)
    actual_time: Mapped[Optional[datetime]] = mapped_column()
    delay_min: Mapped[int] = mapped_column(Integer, default=0)
    executor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    executor_name: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    issue_note: Mapped[Optional[str]] = mapped_column(Text)
    photos_json: Mapped[dict] = mapped_column(JSON, default=list)
    __table_args__ = (Index("idx_bel_plan", "tenant_id", "plan_id"), {"comment": "执行日志"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "plan_id": str(self.plan_id),
            "checkpoint_index": self.checkpoint_index,
            "checkpoint_name": self.checkpoint_name,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
            "actual_time": self.actual_time.isoformat() if self.actual_time else None,
            "delay_min": self.delay_min,
            "executor_name": self.executor_name,
            "status": self.status,
            "issue_note": self.issue_note,
        }
