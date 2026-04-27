"""工作流模板 ORM"""

from typing import Optional

from sqlalchemy import Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeWorkflow(TenantBase):
    __tablename__ = "forge_workflows"

    workflow_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    steps: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    trigger: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    estimated_value_fen: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_execution_ms: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
