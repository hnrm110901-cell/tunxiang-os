"""划菜扫码日志模型 — 记录每次条码扫描确认出品（v342）

用于统计出品时效、超时率、档口效率等 KDS 划菜分析指标。
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DishScanLog(TenantBase):
    """划菜扫码日志

    每次扫码确认出品生成一条记录。
    duration_seconds = scanned_at - ordered_at（从下单到划菜的出品时长）。
    """

    __tablename__ = "dish_scan_logs"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="门店ID")
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="订单ID")
    order_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="订单明细ID")
    barcode: Mapped[str] = mapped_column(String(30), nullable=False, comment="菜品条码")
    dish_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), comment="菜品ID")
    dish_name: Mapped[Optional[str]] = mapped_column(String(100), comment="菜品名称（冗余）")
    dept_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), comment="出品档口ID")
    ordered_at: Mapped[Optional[datetime]] = mapped_column(comment="下单时间")
    scanned_at: Mapped[datetime] = mapped_column(nullable=False, comment="扫码确认时间")
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, comment="出品耗时(秒)=scanned_at-ordered_at")
    scanned_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), comment="扫码操作人ID")

    __table_args__ = (
        Index("idx_scan_logs_store_date", "tenant_id", "store_id", "scanned_at"),
        Index("idx_scan_logs_barcode", "barcode"),
    )
