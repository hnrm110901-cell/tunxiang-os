"""API 密钥 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeApiKey(TenantBase):
    __tablename__ = "forge_api_keys"

    key_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    key_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    permissions: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
