"""
备用金管理ORM模型
PettyCashAccount：备用金账户（每门店一个，含余额状态机）
PettyCashTransaction：流水记录（正负数双向，含对账标志）
PettyCashSettlement：月末核销单（A1Agent自动生成，财务确认）

所有金额字段单位：分(fen)。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase

from .expense_enums import (
    PettyCashAccountStatus,
    PettyCashSettlementStatus,
)

# ─────────────────────────────────────────────────────────────────────────────
# PettyCashAccount — 备用金账户（每个门店唯一）
# ─────────────────────────────────────────────────────────────────────────────


class PettyCashAccount(TenantBase):
    """
    备用金账户。
    每个门店只有一个账户（tenant_id + store_id 联合唯一）。
    余额由应用层在每次写入 transaction 时同步更新，与最新流水的 balance_after 保持一致。
    """

    __tablename__ = "petty_cash_accounts"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店ID，UNIQUE约束确保每门店只有一个备用金账户",
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="品牌ID，用于按品牌汇总备用金报表",
    )
    account_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="门店备用金",
        comment="账户名称，默认'门店备用金'",
    )
    balance: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="当前余额，单位：分(fen)；由应用层与最新流水 balance_after 同步",
    )
    approved_limit: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="审批额度上限，单位：分(fen)；超过此额度的补充申请需额外审批",
    )
    warning_threshold: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="预警阈值，单位：分(fen)；余额低于此值时触发预警通知",
    )
    daily_avg_7d: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="近7日日均消耗，单位：分(fen)；由 A1Agent 定时计算更新，用于预测补充时机",
    )
    keeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="保管人员工ID（通常是店长）；账户冻结时关联离职员工ID",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PettyCashAccountStatus.ACTIVE.value,
        comment="账户状态：active=正常 / frozen=冻结（等待归还）/ closed=已注销",
    )
    frozen_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="冻结原因，status=frozen 时填入，如'店长离职，备用金待归还确认'",
    )
    frozen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="冻结时间",
    )
    last_reconciled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最后一次POS日结对账时间",
    )
    pos_session_ref: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="最后对账关联的POS日结ID，与 tx-ops 日结单关联",
    )

    # ── 关系 ──
    transactions: Mapped[List["PettyCashTransaction"]] = relationship(
        "PettyCashTransaction",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
    )
    settlements: Mapped[List["PettyCashSettlement"]] = relationship(
        "PettyCashSettlement",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PettyCashTransaction — 备用金流水
# ─────────────────────────────────────────────────────────────────────────────


class PettyCashTransaction(TenantBase):
    """
    备用金流水记录。
    正数=收入（补充/归还/期初），负数=支出（日常/日结调整）。
    每次写入时，amount 和 balance_after 必须在同一数据库事务内与账户余额保持一致。
    """

    __tablename__ = "petty_cash_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("petty_cash_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="关联备用金账户ID",
    )
    transaction_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment=(
            "流水类型：replenishment=补充 / return_from_keeper=员工归还 / "
            "opening_balance=期初录入 / daily_use=日常支出 / "
            "pos_reconcile_adjust=日结调整 / freeze_reserve=冻结记录"
        ),
    )
    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="交易金额，单位：分(fen)；正数=收入，负数=支出",
    )
    balance_after: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="本次交易后账户余额，单位：分(fen)；与 petty_cash_accounts.balance 最新值保持一致",
    )
    description: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="流水描述，如'采购食材'、'补充备用金'",
    )
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联业务单据ID（费用申请ID/POS日结ID/核销单ID），可为 NULL",
    )
    reference_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="关联单据类型：expense_application / pos_session / settlement",
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="操作人员工ID，记录谁录入了这笔流水",
    )
    is_reconciled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已核销：false=未核销（月末核销单中标红提示），true=已纳入核销单确认",
    )
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="核销时间",
    )
    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=func.current_date(),
        comment="费用发生日期（业务日期），用于月末核销区间统计，可能早于系统录入时间 created_at",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="备注，如差异说明、特殊情况",
    )

    # ── 关系 ──
    account: Mapped["PettyCashAccount"] = relationship(
        "PettyCashAccount",
        back_populates="transactions",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PettyCashSettlement — 月末核销单
# ─────────────────────────────────────────────────────────────────────────────


class PettyCashSettlement(TenantBase):
    """
    月末核销单。
    每个账户每自然月一张（tenant_id + account_id + settlement_month 唯一）。
    由 A1Agent 自动生成 draft，财务人工确认后关闭。
    """

    __tablename__ = "petty_cash_settlements"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("petty_cash_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="关联备用金账户ID",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店ID，冗余存储便于按门店查询核销单",
    )
    settlement_month: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        comment="核销月份，格式 YYYY-MM，如 2026-04",
    )
    period_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="统计期间起始日期（当月1日）",
    )
    period_end: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="统计期间截止日期（当月最后一日）",
    )
    opening_balance: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="期初余额，单位：分(fen)；等于上月核销单 closing_balance，首月为期初录入流水的 balance_after",
    )
    total_income: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="本期收入合计，单位：分(fen)；统计期间内所有 amount>0 流水之和",
    )
    total_expense: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="本期支出合计，单位：分(fen)；统计期间内所有 amount<0 流水绝对值之和",
    )
    closing_balance: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="期末余额，单位：分(fen)；= opening_balance + total_income - total_expense",
    )
    reconciled_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已核销流水笔数（is_reconciled=true 的 transactions 数量）",
    )
    unreconciled_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="未核销流水笔数（is_reconciled=false），财务核销单中标红提示",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PettyCashSettlementStatus.DRAFT.value,
        comment="核销单状态：draft=待确认 / submitted=已提交财务 / confirmed=财务已确认 / closed=已归档",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="核销单备注，财务确认时可填写说明",
    )
    generated_by: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="a1_agent",
        comment="生成方式：a1_agent=系统自动生成 / manual=财务手工创建",
    )
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="财务确认人员工ID；status=confirmed 时必填",
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="财务确认时间",
    )

    # ── 关系 ──
    account: Mapped["PettyCashAccount"] = relationship(
        "PettyCashAccount",
        back_populates="settlements",
        lazy="select",
    )
