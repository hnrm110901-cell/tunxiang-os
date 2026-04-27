"""生态联盟上架 ORM"""

import uuid
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeAllianceListing(TenantBase):
    __tablename__ = "forge_alliance_listings"

    listing_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    owner_tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    sharing_mode: Mapped[str] = mapped_column(String(20), default="invited")
    shared_tenants: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    revenue_share_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.7)
    platform_fee_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.3)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    total_revenue_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
