"""证据卡片 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeEvidenceCard(TenantBase):
    __tablename__ = "forge_evidence_cards"

    card_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    card_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence_data = mapped_column(JSONB, default={})
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    verified_by: Mapped[str] = mapped_column(String(100), default="")
    verification_method: Mapped[str] = mapped_column(String(20), default="auto")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
