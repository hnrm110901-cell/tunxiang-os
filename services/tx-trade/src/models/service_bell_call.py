"""服务铃呼叫记录模型"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ServiceBellCall(TenantBase):
    __tablename__ = "service_bell_calls"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    table_no: Mapped[str] = mapped_column(String(20), nullable=False)
    call_type: Mapped[str] = mapped_column(String(50), nullable=False)
    call_type_label: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    called_at: Mapped[datetime] = mapped_column(nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column()
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
