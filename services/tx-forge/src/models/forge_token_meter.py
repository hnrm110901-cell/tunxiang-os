"""Token 计量 ORM"""

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeTokenMeter(TenantBase):
    __tablename__ = "forge_token_meters"

    app_id: Mapped[str] = mapped_column(String(50), nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    budget_fen: Mapped[int] = mapped_column(Integer, default=0)
    alert_threshold: Mapped[int] = mapped_column(Integer, default=80)
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
