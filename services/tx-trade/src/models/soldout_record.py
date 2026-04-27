"""沽清记录模型"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class SoldoutRecord(TenantBase):
    __tablename__ = "soldout_records"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    dish_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    dish_name: Mapped[str] = mapped_column(String(100), nullable=False)
    soldout_at: Mapped[datetime] = mapped_column(nullable=False)
    restore_at: Mapped[Optional[datetime]] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(200))
    reported_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="kds")
    sync_status: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=lambda: {"pos": False, "miniapp": False, "kds": False}
    )
