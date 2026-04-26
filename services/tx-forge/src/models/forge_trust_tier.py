"""信任等级 ORM"""

from sqlalchemy import String, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeTrustTier(TenantBase):
    __tablename__ = "forge_trust_tiers"

    tier_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    tier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    data_access: Mapped[str] = mapped_column(String(20), nullable=False)
    action_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    financial_access: Mapped[bool] = mapped_column(Boolean, default=False)
    requirements: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
