"""
D8 收货质检模型 — Should-Fix P1

流程：创建收货单 → 逐项质检（pass/reject/partial）→ 过账入库

金额「分」存储；拒收部分自动关联 WasteEvent。
"""

import enum
import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class QCStatus(str, enum.Enum):
    """质检状态"""

    PENDING = "pending"      # 待质检
    PASS = "pass"            # 全部通过
    REJECT = "reject"        # 全部拒收
    PARTIAL = "partial"      # 部分接收


class ReceiptStatus(str, enum.Enum):
    """收货单状态"""

    DRAFT = "draft"
    QC_IN_PROGRESS = "qc_in_progress"
    POSTED = "posted"           # 已过账入库
    CANCELLED = "cancelled"


class GoodsReceipt(Base, TimestampMixin):
    """收货单主档"""

    __tablename__ = "goods_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id = Column(String, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    receipt_no = Column(String(50), nullable=False, unique=True, index=True)

    total_amount_fen = Column(Integer, default=0, nullable=False)   # 实收总金额（分）
    received_by = Column(String(50), nullable=False)

    qc_status = Column(String(20), default=QCStatus.PENDING.value, nullable=False)
    status = Column(String(20), default=ReceiptStatus.DRAFT.value, nullable=False, index=True)

    notes = Column(Text, nullable=True)
    posted_at = Column(DateTime, nullable=True)

    # 关系
    items = relationship(
        "GoodsReceiptItem",
        back_populates="receipt",
        cascade="all, delete-orphan",
    )

    @property
    def total_amount_yuan(self) -> float:
        return round((self.total_amount_fen or 0) / 100, 2)


class GoodsReceiptItem(Base, TimestampMixin):
    """收货单明细"""

    __tablename__ = "goods_receipt_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_id = Column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingredient_id = Column(String(50), nullable=False, index=True)

    ordered_qty = Column(Numeric(12, 3), nullable=False)
    received_qty = Column(Numeric(12, 3), nullable=False, default=0)
    rejected_qty = Column(Numeric(12, 3), nullable=False, default=0)

    unit = Column(String(20), nullable=True)
    unit_cost_fen = Column(Integer, nullable=True)   # 单价（分）

    qc_status = Column(String(20), default=QCStatus.PENDING.value, nullable=False)
    qc_remark = Column(Text, nullable=True)

    # 冷链与溯源字段
    temperature = Column(Numeric(5, 2), nullable=True)   # 入库温度 ℃
    prod_date = Column(Date, nullable=True)              # 生产日期
    expiry_date = Column(Date, nullable=True)            # 保质期

    waste_event_id = Column(UUID(as_uuid=True), nullable=True)  # 拒收对应的损耗事件

    receipt = relationship("GoodsReceipt", back_populates="items")

    @property
    def unit_cost_yuan(self) -> float:
        return round((self.unit_cost_fen or 0) / 100, 2)
