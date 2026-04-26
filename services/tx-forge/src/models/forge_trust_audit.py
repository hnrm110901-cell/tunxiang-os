"""信任审计 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeTrustAudit(TenantBase):
    __tablename__ = "forge_trust_audits"

    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    previous_tier: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    new_tier: Mapped[str] = mapped_column(String(10), nullable=False)
    audit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    auditor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    audited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
