"""Token 定价 ORM"""

from datetime import datetime

from sqlalchemy import String, Integer, Numeric, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeTokenPrice(TenantBase):
    __tablename__ = "forge_token_prices"

    app_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    input_price_per_1k_fen: Mapped[int] = mapped_column(Integer, default=0)
    output_price_per_1k_fen: Mapped[int] = mapped_column(Integer, default=0)
    markup_rate = mapped_column(Numeric(5, 4), default=0)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
