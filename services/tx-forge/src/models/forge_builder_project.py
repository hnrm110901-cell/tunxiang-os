"""低代码构建器项目 ORM"""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeBuilderProject(TenantBase):
    __tablename__ = "forge_builder_projects"

    project_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_type: Mapped[str] = mapped_column(String(30), nullable=False)
    canvas: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    generated_code: Mapped[str] = mapped_column(Text, default="")
    preview_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
