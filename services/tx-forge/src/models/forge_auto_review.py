"""自动审核记录 ORM"""

from typing import Optional

from sqlalchemy import String, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeAutoReview(TenantBase):
    __tablename__ = "forge_auto_reviews"

    review_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    auto_checks: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    ai_suggestions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    human_required: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    auto_pass_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    auto_score: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
