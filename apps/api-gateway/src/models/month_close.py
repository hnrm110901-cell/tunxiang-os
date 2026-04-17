"""月结/年结（D7 Nice-to-Have）

MonthCloseLog     ── 月结/年结执行日志（status=pending|closed|reopened|year_closed）
TrialBalanceSnapshot ── 月末/年末试算平衡表快照（金额字段以「分」存储）

Rule 6: 所有金额 *_fen 字段提供 *_yuan @property 转换。
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


def _fen_to_yuan(v):
    return round((v or 0) / 100, 2) if v is not None else 0


class MonthCloseLog(Base, TimestampMixin):
    """月结/年结执行日志

    year_month 格式:
      - 月结: YYYYMM  (如 202603)
      - 年结: YYYY00  (年结统一月份位补 00 以示区分)
    status:
      - pending       预检通过，未执行
      - closed        月结已完成
      - year_closed   年结已完成
      - reopened      反结账（仅老板可操作）
    """

    __tablename__ = "month_close_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    year_month = Column(String(6), nullable=False, index=True)  # YYYYMM / YYYY00

    status = Column(String(20), nullable=False, default="pending", index=True)

    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(UUID(as_uuid=True), nullable=True)
    reopened_at = Column(DateTime, nullable=True)
    reopened_by = Column(UUID(as_uuid=True), nullable=True)
    reason = Column(Text, nullable=True)

    # 月/年结执行时的报表快照（trial balance / income statement / balance sheet）
    snapshot_json = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("uq_close_store_ym", "store_id", "year_month", unique=True),
    )


class TrialBalanceSnapshot(Base):
    """月末试算平衡表快照 — 按科目冻结期末余额"""

    __tablename__ = "trial_balance_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    year_month = Column(String(6), nullable=False, index=True)
    account_code = Column(String(20), nullable=False, index=True)
    account_name = Column(String(100), nullable=False)

    opening_debit_fen = Column(Integer, nullable=False, default=0)
    opening_credit_fen = Column(Integer, nullable=False, default=0)
    period_debit_fen = Column(Integer, nullable=False, default=0)
    period_credit_fen = Column(Integer, nullable=False, default=0)
    closing_debit_fen = Column(Integer, nullable=False, default=0)
    closing_credit_fen = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("uq_tb_store_ym_code", "store_id", "year_month", "account_code", unique=True),
    )

    @property
    def opening_debit_yuan(self):
        return _fen_to_yuan(self.opening_debit_fen)

    @property
    def opening_credit_yuan(self):
        return _fen_to_yuan(self.opening_credit_fen)

    @property
    def period_debit_yuan(self):
        return _fen_to_yuan(self.period_debit_fen)

    @property
    def period_credit_yuan(self):
        return _fen_to_yuan(self.period_credit_fen)

    @property
    def closing_debit_yuan(self):
        return _fen_to_yuan(self.closing_debit_fen)

    @property
    def closing_credit_yuan(self):
        return _fen_to_yuan(self.closing_credit_fen)
