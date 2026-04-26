"""安装记录 ORM"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeInstallation(TenantBase):
    __tablename__ = "forge_installations"

    install_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    store_ids: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    installed_version: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uninstalled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
