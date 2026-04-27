"""收入流水 ORM"""

import uuid

from sqlalchemy import BigInteger, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeRevenueEntry(TenantBase):
    __tablename__ = "forge_revenue_entries"

    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payer_tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    developer_payout_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    pricing_model: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
