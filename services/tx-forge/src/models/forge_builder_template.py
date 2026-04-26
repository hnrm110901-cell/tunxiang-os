"""低代码构建器模板 ORM"""

from typing import Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeBuilderTemplate(TenantBase):
    __tablename__ = "forge_builder_templates"

    template_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    template_type: Mapped[str] = mapped_column(String(30), nullable=False)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scaffold_code: Mapped[str] = mapped_column(Text, nullable=False)
    required_ontology: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    example_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
