"""应用 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeApp(TenantBase):
    __tablename__ = "forge_apps"

    app_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    icon_url: Mapped[str] = mapped_column(String(500), default="")
    screenshots: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    pricing_model: Mapped[str] = mapped_column(String(30), default="free")
    price_fen: Mapped[int] = mapped_column(Integer, default=0)
    price_display: Mapped[str] = mapped_column(String(50), default="免费")
    permissions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    api_endpoints: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    webhook_urls: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[str] = mapped_column(String(30), default="0.0.1")
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_total_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
