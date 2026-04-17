"""
AR/AP 应收应付台账模型 — D7-P0 Must-Fix

包含：
  - AccountReceivable: 应收账款（客户/单号/金额分/到期日/状态）
  - ARPayment: 应收收款记录
  - AccountPayable: 应付账款（供应商/单号/金额分/到期日/状态）
  - APPayment: 应付付款记录

金额字段统一以「分」存储，通过 @property *_yuan 提供元级别展示。
"""

import enum
import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class ARStatus(str, enum.Enum):
    """应收状态"""

    OPEN = "open"              # 未收
    PARTIAL = "partial"        # 部分收款
    CLOSED = "closed"          # 已结清
    WRITTEN_OFF = "written_off"  # 坏账核销
    OVERDUE = "overdue"        # 逾期（定时任务标记）


class APStatus(str, enum.Enum):
    """应付状态"""

    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


def _fen_to_yuan(fen_value):
    return round((fen_value or 0) / 100, 2) if fen_value is not None else 0


# ──────────────────────────── 应收账款 ────────────────────────────


class AccountReceivable(Base, TimestampMixin):
    """应收账款（AR）— 挂账结算/企业客户赊销/对公收款等场景"""

    __tablename__ = "accounts_receivable"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # 客户信息（可能是挂账账户/企业会员/散客）
    customer_type = Column(String(30), nullable=False, default="credit_account")  # credit_account/enterprise/other
    customer_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    customer_name = Column(String(200), nullable=False)

    ar_no = Column(String(40), unique=True, nullable=False, index=True)  # AR+YYYYMMDD+6位
    source_bill_id = Column(UUID(as_uuid=True), nullable=True, index=True)    # 账单ID
    source_ref = Column(String(100), nullable=True)                           # 单据号

    # 金额（分）
    amount_fen = Column(Integer, nullable=False)          # 应收总额
    received_fen = Column(Integer, nullable=False, default=0)  # 已收

    issue_date = Column(Date, nullable=False, default=date_type.today, index=True)
    due_date = Column(Date, nullable=True, index=True)

    status = Column(Enum(ARStatus), nullable=False, default=ARStatus.OPEN, index=True)
    remark = Column(String(500), nullable=True)
    extras = Column(JSONB, nullable=True)

    payments = relationship("ARPayment", back_populates="ar", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ar_customer_status", "customer_id", "status"),
        Index("idx_ar_due_status", "due_date", "status"),
        Index("idx_ar_store_status", "store_id", "status"),
    )

    @property
    def amount_yuan(self):
        return _fen_to_yuan(self.amount_fen)

    @property
    def received_yuan(self):
        return _fen_to_yuan(self.received_fen)

    @property
    def outstanding_fen(self):
        return max(0, (self.amount_fen or 0) - (self.received_fen or 0))

    @property
    def outstanding_yuan(self):
        return _fen_to_yuan(self.outstanding_fen)


class ARPayment(Base):
    """应收收款记录"""

    __tablename__ = "ar_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts_receivable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount_fen = Column(Integer, nullable=False)
    payment_date = Column(Date, nullable=False, default=date_type.today)
    payment_method = Column(String(30), nullable=True)  # bank_transfer/cash/wechat/...
    reference_no = Column(String(100), nullable=True)   # 对方单号
    operator_id = Column(UUID(as_uuid=True), nullable=True)
    remark = Column(String(500), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    ar = relationship("AccountReceivable", back_populates="payments")

    @property
    def amount_yuan(self):
        return _fen_to_yuan(self.amount_fen)


# ──────────────────────────── 应付账款 ────────────────────────────


class AccountPayable(Base, TimestampMixin):
    """应付账款（AP）— 供应商采购/外包服务等"""

    __tablename__ = "accounts_payable"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    supplier_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    supplier_name = Column(String(200), nullable=False)

    ap_no = Column(String(40), unique=True, nullable=False, index=True)       # AP+YYYYMMDD+6位
    source_po_id = Column(UUID(as_uuid=True), nullable=True, index=True)      # 采购单ID
    source_ref = Column(String(100), nullable=True)

    amount_fen = Column(Integer, nullable=False)
    paid_fen = Column(Integer, nullable=False, default=0)

    issue_date = Column(Date, nullable=False, default=date_type.today, index=True)
    due_date = Column(Date, nullable=True, index=True)

    status = Column(Enum(APStatus), nullable=False, default=APStatus.OPEN, index=True)
    remark = Column(String(500), nullable=True)
    extras = Column(JSONB, nullable=True)

    payments = relationship("APPayment", back_populates="ap", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ap_supplier_status", "supplier_id", "status"),
        Index("idx_ap_due_status", "due_date", "status"),
        Index("idx_ap_store_status", "store_id", "status"),
    )

    @property
    def amount_yuan(self):
        return _fen_to_yuan(self.amount_fen)

    @property
    def paid_yuan(self):
        return _fen_to_yuan(self.paid_fen)

    @property
    def outstanding_fen(self):
        return max(0, (self.amount_fen or 0) - (self.paid_fen or 0))

    @property
    def outstanding_yuan(self):
        return _fen_to_yuan(self.outstanding_fen)


class APPayment(Base):
    """应付付款记录"""

    __tablename__ = "ap_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ap_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts_payable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount_fen = Column(Integer, nullable=False)
    payment_date = Column(Date, nullable=False, default=date_type.today)
    payment_method = Column(String(30), nullable=True)
    reference_no = Column(String(100), nullable=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True)
    remark = Column(String(500), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    ap = relationship("AccountPayable", back_populates="payments")

    @property
    def amount_yuan(self):
        return _fen_to_yuan(self.amount_fen)
