"""运行时违规 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeRuntimeViolation(TenantBase):
    __tablename__ = "forge_runtime_violations"

    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    violation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="P2")
    context: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
