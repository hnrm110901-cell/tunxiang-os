"""应用版本 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeAppVersion(TenantBase):
    __tablename__ = "forge_app_versions"

    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    package_url: Mapped[str] = mapped_column(String(500), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    min_platform_version: Mapped[str] = mapped_column(String(30), default="1.0.0")
    status: Mapped[str] = mapped_column(String(20), default="submitted")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
