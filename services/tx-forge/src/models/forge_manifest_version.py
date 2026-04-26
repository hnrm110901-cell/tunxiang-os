"""Manifest 版本 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeManifestVersion(TenantBase):
    __tablename__ = "forge_manifest_versions"

    manifest_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    forge_version: Mapped[str] = mapped_column(String(20), default="1.5")
    manifest_content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
