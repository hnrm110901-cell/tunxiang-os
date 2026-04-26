"""沙箱环境 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeSandbox(TenantBase):
    __tablename__ = "forge_sandboxes"

    sandbox_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    sandbox_url: Mapped[str] = mapped_column(String(500), nullable=False)
    test_tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    test_api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    test_data: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
