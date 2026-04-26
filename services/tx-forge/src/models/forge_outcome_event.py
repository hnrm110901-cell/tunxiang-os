"""成果事件 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, BigInteger, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeOutcomeEvent(TenantBase):
    __tablename__ = "forge_outcome_events"

    outcome_id: Mapped[str] = mapped_column(String(50), nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    store_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    decision_log_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome_data = mapped_column(JSONB, default={})
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    revenue_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    attributed_agents = mapped_column(JSONB, default=[])
