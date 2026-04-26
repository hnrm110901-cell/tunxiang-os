"""工作流执行记录 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeWorkflowRun(TenantBase):
    __tablename__ = "forge_workflow_runs"

    workflow_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_data: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="running")
    steps_completed: Mapped[int] = mapped_column(Integer, default=0)
    steps_total: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
