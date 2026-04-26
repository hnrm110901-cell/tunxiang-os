"""Ontology 绑定 ORM"""

from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeOntologyBinding(TenantBase):
    __tablename__ = "forge_ontology_bindings"
    __table_args__ = (
        UniqueConstraint("app_id", "entity_name", name="uq_ontology_binding"),
    )

    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_name: Mapped[str] = mapped_column(String(50), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    allowed_fields: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    constraints: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
