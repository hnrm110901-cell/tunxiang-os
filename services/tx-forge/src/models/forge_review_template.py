"""审核模板 ORM"""

from typing import Optional

from sqlalchemy import String, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeReviewTemplate(TenantBase):
    __tablename__ = "forge_review_templates"

    template_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_category: Mapped[str] = mapped_column(String(50), nullable=False)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    auto_checks: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    human_checks: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    pass_threshold: Mapped[int] = mapped_column(Integer, default=80)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
