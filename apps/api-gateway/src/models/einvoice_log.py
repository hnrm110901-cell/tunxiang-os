"""
电子发票开票日志 — D7-P0 Must-Fix Task 3

记录每次结算触发开票的请求/响应/状态，支持失败容错重试与自助补录。
与既有 e_invoice 表（EInvoice）并存：前者是正式开票档案，本表聚焦"结算触发"动作。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class EInvoiceLogStatus(str, enum.Enum):
    """开票日志状态"""

    PENDING = "pending"         # 等待抬头补录
    ISSUING = "issuing"         # 开票中
    ISSUED = "issued"           # 开票成功
    FAILED = "failed"           # 开票失败
    CANCELLED = "cancelled"     # 已取消


class EInvoiceLog(Base, TimestampMixin):
    """电子发票开票日志"""

    __tablename__ = "einvoice_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    bill_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # 短码与自助链接（未提供抬头时使用，复用 e_receipt 模式）
    short_code = Column(String(20), nullable=True, unique=True, index=True)
    self_service_url = Column(Text, nullable=True)

    # 购方信息（开票后填充）
    buyer_name = Column(String(200), nullable=True)
    buyer_tax_number = Column(String(30), nullable=True)
    buyer_phone = Column(String(30), nullable=True)
    buyer_email = Column(String(100), nullable=True)

    # 发票信息
    invoice_no = Column(String(30), nullable=True, index=True)
    invoice_code = Column(String(20), nullable=True)
    pdf_url = Column(Text, nullable=True)

    amount_fen = Column(Integer, nullable=False, default=0)

    status = Column(Enum(EInvoiceLogStatus), nullable=False, default=EInvoiceLogStatus.PENDING, index=True)
    platform = Column(String(20), nullable=True)   # baiwang/nuonuo/...

    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    issued_at = Column(DateTime, nullable=True)
    extras = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_einvoice_log_bill", "bill_id"),
        Index("idx_einvoice_log_status", "status"),
    )

    @property
    def amount_yuan(self):
        return round((self.amount_fen or 0) / 100, 2)
