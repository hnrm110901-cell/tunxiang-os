"""
会计凭证与科目表模型 — D7-P0 Must-Fix

本模块实现复式记账最小闭环：
  - ChartOfAccounts: 科目表（资产/负债/权益/收入/成本/费用）
  - Voucher: 记账凭证头（凭证号/日期/摘要/制单人/状态）
  - VoucherEntry: 凭证分录（借/贷方 以「分」存储）

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
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


# ──────────────────────────── Enums ────────────────────────────


class AccountType(str, enum.Enum):
    """会计科目类型"""

    ASSET = "asset"          # 资产
    LIABILITY = "liability"  # 负债
    EQUITY = "equity"        # 权益
    REVENUE = "revenue"      # 收入
    COST = "cost"            # 成本
    EXPENSE = "expense"      # 费用


class VoucherStatus(str, enum.Enum):
    """凭证状态"""

    DRAFT = "draft"     # 草稿
    POSTED = "posted"   # 已过账
    VOID = "void"       # 作废


# ──────────────────────────── Helper ────────────────────────────


def _fen_to_yuan(fen_value):
    """分转元"""
    return round((fen_value or 0) / 100, 2) if fen_value is not None else 0


# ──────────────────────────── Models ────────────────────────────


class ChartOfAccounts(Base, TimestampMixin):
    """会计科目表

    采用三级/四级科目代码（如 1002 银行存款 / 2203 预收账款）。
    parent_code 指向上级科目代码，便于构建科目树。
    """

    __tablename__ = "chart_of_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 多品牌隔离，null=全局默认

    code = Column(String(20), nullable=False, index=True)    # 科目代码 1002
    name = Column(String(100), nullable=False)               # 科目名称 银行存款
    account_type = Column(Enum(AccountType), nullable=False)
    parent_code = Column(String(20), nullable=True, index=True)

    # 借贷方向（debit=借方增加；credit=贷方增加）
    # 资产/成本/费用：借方；负债/权益/收入：贷方
    normal_balance = Column(String(10), nullable=False, default="debit")

    description = Column(Text, nullable=True)
    is_active = Column(String(10), nullable=False, default="true")

    __table_args__ = (
        Index("uq_coa_brand_code", "brand_id", "code", unique=True),
    )


class Voucher(Base, TimestampMixin):
    """记账凭证头"""

    __tablename__ = "vouchers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    voucher_no = Column(String(40), unique=True, nullable=False, index=True)  # 凭证号 PZ-YYYYMMDD-NNNN
    voucher_date = Column(Date, nullable=False, default=date_type.today, index=True)
    summary = Column(String(500), nullable=False)     # 摘要

    status = Column(Enum(VoucherStatus), nullable=False, default=VoucherStatus.POSTED, index=True)

    # 借贷合计（分）— 过账时校验必须相等
    total_debit_fen = Column(Integer, nullable=False, default=0)
    total_credit_fen = Column(Integer, nullable=False, default=0)

    # 业务关联（追溯到源单据，便于审计）
    source_type = Column(String(50), nullable=True, index=True)   # stored_value_recharge / ar_create / ap_pay...
    source_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_by = Column(UUID(as_uuid=True), nullable=True)        # 制单人
    posted_by = Column(UUID(as_uuid=True), nullable=True)         # 过账人
    posted_at = Column(DateTime, nullable=True)
    void_reason = Column(String(500), nullable=True)
    extras = Column(JSONB, nullable=True)

    entries = relationship(
        "VoucherEntry",
        back_populates="voucher",
        cascade="all, delete-orphan",
        order_by="VoucherEntry.line_no",
    )

    __table_args__ = (
        Index("idx_voucher_date_status", "voucher_date", "status"),
        Index("idx_voucher_source", "source_type", "source_id"),
    )

    @property
    def total_debit_yuan(self):
        return _fen_to_yuan(self.total_debit_fen)

    @property
    def total_credit_yuan(self):
        return _fen_to_yuan(self.total_credit_fen)


class VoucherEntry(Base):
    """凭证分录（借/贷方行）"""

    __tablename__ = "voucher_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    voucher_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vouchers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    line_no = Column(Integer, nullable=False, default=1)     # 行号
    account_code = Column(String(20), nullable=False, index=True)  # 科目代码
    account_name = Column(String(100), nullable=False)             # 冗余科目名称（凭证打印）

    # 借贷金额（分）— 一个分录行只允许借或贷其一非零
    debit_fen = Column(Integer, nullable=False, default=0)
    credit_fen = Column(Integer, nullable=False, default=0)

    summary = Column(String(500), nullable=True)             # 分录摘要
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    voucher = relationship("Voucher", back_populates="entries")

    __table_args__ = (
        Index("idx_ventry_account_code", "account_code"),
    )

    @property
    def debit_yuan(self):
        return _fen_to_yuan(self.debit_fen)

    @property
    def credit_yuan(self):
        return _fen_to_yuan(self.credit_fen)
