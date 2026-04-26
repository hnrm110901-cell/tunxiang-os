"""运行时策略 ORM"""

from typing import Optional

from sqlalchemy import String, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeRuntimePolicy(TenantBase):
    __tablename__ = "forge_runtime_policies"

    app_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(10), default="T0")
    allowed_entities: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    allowed_actions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    denied_actions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    token_budget_daily: Mapped[int] = mapped_column(Integer, default=100000)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    sandbox_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_downgrade_threshold: Mapped[int] = mapped_column(Integer, default=3)
