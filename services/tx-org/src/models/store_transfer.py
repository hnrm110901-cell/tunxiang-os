"""门店借调单模型"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class StoreTransferOrder(TenantBase):
    """门店借调单"""

    __tablename__ = "store_transfer_orders"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True, comment="员工ID")
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="员工姓名")
    from_store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True, comment="原门店ID")
    from_store_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="原门店名称")
    to_store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="借调目标门店ID"
    )
    to_store_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="借调目标门店名称")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="借调开始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="借调结束日期")
    reason: Mapped[str] = mapped_column(Text, default="", comment="借调原因")
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="状态: pending/approved/active/completed/cancelled",
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="审批人ID")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="审批时间")
