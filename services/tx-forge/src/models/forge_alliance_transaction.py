"""生态联盟交易记录 ORM"""

import uuid

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeAllianceTransaction(TenantBase):
    __tablename__ = "forge_alliance_transactions"

    listing_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    consumer_tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_share_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_share_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), default="subscription")
