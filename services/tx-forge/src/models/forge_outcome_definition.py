"""成果定义 ORM"""

from sqlalchemy import String, Text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeOutcomeDefinition(TenantBase):
    __tablename__ = "forge_outcome_definitions"

    outcome_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome_type: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    measurement_method: Mapped[str] = mapped_column(String(20), nullable=False)
    price_fen_per_outcome: Mapped[int] = mapped_column(Integer, default=0)
    attribution_window_hours: Mapped[int] = mapped_column(Integer, default=24)
    verification_method: Mapped[str] = mapped_column(String(20), default="auto")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
