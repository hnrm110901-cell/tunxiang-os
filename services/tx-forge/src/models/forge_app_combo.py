"""应用组合 ORM"""

from sqlalchemy import String, Text, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeAppCombo(TenantBase):
    __tablename__ = "forge_app_combos"

    combo_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    combo_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    app_ids = mapped_column(JSONB, default=[])
    use_case: Mapped[str] = mapped_column(String(200), default="")
    target_role: Mapped[str] = mapped_column(String(50), default="")
    synergy_score = mapped_column(Numeric(5, 2), default=0)
    evidence = mapped_column(JSONB, default={})
    install_count: Mapped[int] = mapped_column(Integer, default=0)
