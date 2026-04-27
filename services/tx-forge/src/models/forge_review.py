"""审核记录 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeReview(TenantBase):
    __tablename__ = "forge_reviews"

    review_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    app_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewer_id: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    checklist: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
