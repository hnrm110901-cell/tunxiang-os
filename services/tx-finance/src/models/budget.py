"""预算管理模型 — 预算编制 + 执行跟踪

Budget: 预算表（按门店/部门/期间/类别）
BudgetExecution: 预算执行记录（实际发生 vs 预算）

所有金额单位：分（fen）。
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class Budget(TenantBase):
    """预算表 — 按门店/部门/期间/类别定义预算目标

    status 流转: draft → approved → active → closed
    """

    __tablename__ = "budgets"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="门店ID",
    )
    department: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="部门（前厅/后厨/管理/全店）",
    )
    period: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="周期类型: monthly / quarterly / yearly",
    )
    period_start: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="预算期间起始日",
    )
    period_end: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="预算期间截止日",
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="预算类别: revenue / cost / labor / material / marketing / overhead",
    )
    budget_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
        comment="预算金额(分)",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft",
        comment="状态: draft / approved / active / closed",
    )
    note: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="备注",
    )

    # 关联
    executions: Mapped[list["BudgetExecution"]] = relationship(
        back_populates="budget", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_budgets_tenant_store", "tenant_id", "store_id"),
        Index("ix_budgets_tenant_period", "tenant_id", "period_start", "period_end"),
        Index("ix_budgets_tenant_store_category", "tenant_id", "store_id", "category"),
    )


class BudgetExecution(TenantBase):
    """预算执行记录 — 记录实际发生金额，与预算对比计算偏差"""

    __tablename__ = "budget_executions"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联预算ID",
    )
    actual_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
        comment="实际发生金额(分)",
    )
    variance_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
        comment="偏差=实际-预算(分)，正值表示超支",
    )
    variance_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="偏差率=(实际-预算)/预算",
    )
    recorded_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="记录日期",
    )
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="来源类型: order / purchase / payroll / expense",
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="说明",
    )

    # 关联
    budget: Mapped["Budget"] = relationship(back_populates="executions")

    __table_args__ = (
        Index("ix_budget_executions_tenant_budget", "tenant_id", "budget_id"),
        Index("ix_budget_executions_tenant_date", "tenant_id", "recorded_date"),
    )
