"""
预算管理 ORM 模型
包含：Budget（预算主表）、BudgetAllocation（科目分配）、
      BudgetAdjustment（调整记录）、BudgetSnapshot（月末快照）

设计说明：
- 所有金额字段单位为分(fen)，BigInteger 存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离
- budget_month=None 表示年度预算，有值(1-12)表示月度预算
- store_id=None 表示集团预算
- 与 v242 迁移文件表结构完全对应
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# Budget — 预算主表
# ─────────────────────────────────────────────────────────────────────────────


class Budget(TenantBase):
    """
    预算主表
    支持年度预算（budget_month=None）和月度预算（budget_month=1-12）。
    store_id=None 表示集团/品牌级预算，有值表示门店级预算。
    total_amount / used_amount 单位均为分(fen)。
    """

    __tablename__ = "budgets"

    budget_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="预算名称")
    budget_year: Mapped[int] = mapped_column(Integer, nullable=False, comment="预算年份，如 2026")
    budget_month: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="预算月份（NULL=年度预算，1-12=月度预算）"
    )
    budget_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="expense",
        server_default="expense",
        comment="预算类型：expense/travel/procurement",
    )

    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="关联门店ID（NULL=集团预算）"
    )
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="部门")

    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="预算总额（分）")
    used_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0", comment="已使用金额（分），原子更新"
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        comment="预算状态：draft/active/locked/expired",
    )

    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="审批人员工ID")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="创建人员工ID")

    # 关系
    allocations: Mapped[List["BudgetAllocation"]] = relationship(
        "BudgetAllocation",
        back_populates="budget",
        cascade="all, delete-orphan",
        lazy="select",
    )
    adjustments: Mapped[List["BudgetAdjustment"]] = relationship(
        "BudgetAdjustment",
        back_populates="budget",
        cascade="all, delete-orphan",
        lazy="select",
    )
    snapshots: Mapped[List["BudgetSnapshot"]] = relationship(
        "BudgetSnapshot",
        back_populates="budget",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# BudgetAllocation — 科目分配
# ─────────────────────────────────────────────────────────────────────────────


class BudgetAllocation(TenantBase):
    """
    预算科目分配
    将预算总额按费用科目（category_code）拆分分配。
    allocated_amount / used_amount 单位均为分(fen)。
    """

    __tablename__ = "budget_allocations"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属预算ID",
    )
    category_code: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="费用科目代码（对应 ExpenseCategoryCode）"
    )
    allocated_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="分配金额（分）")
    used_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0", comment="已使用金额（分）"
    )

    # 关系
    budget: Mapped["Budget"] = relationship("Budget", back_populates="allocations")


# ─────────────────────────────────────────────────────────────────────────────
# BudgetAdjustment — 预算调整记录
# ─────────────────────────────────────────────────────────────────────────────


class BudgetAdjustment(TenantBase):
    """
    预算调整记录
    每次对预算额度的调增/调减/重新分配都产生一条记录，形成完整审计轨迹。
    amount 单位为分(fen)，正值表示增加，负值表示减少。
    """

    __tablename__ = "budget_adjustments"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属预算ID",
    )
    adjustment_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="调整类型：increase/decrease/reallocate"
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="调整金额（分，正增负减）")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="调整原因")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="审批人员工ID")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, comment="创建人员工ID")

    # 关系
    budget: Mapped["Budget"] = relationship("Budget", back_populates="adjustments")


# ─────────────────────────────────────────────────────────────────────────────
# BudgetSnapshot — 月末快照
# ─────────────────────────────────────────────────────────────────────────────


class BudgetSnapshot(TenantBase):
    """
    预算月末快照
    在月末（或手动触发）时对当前预算状态进行完整存档，支持历史趋势分析。
    execution_rate 为执行率，如 0.8567 表示已使用 85.67%。
    snapshot_data 存储完整快照（含分配明细），JSONB 格式。
    """

    __tablename__ = "budget_snapshots"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属预算ID",
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    total_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="快照时预算总额（分）")
    used_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="快照时已使用金额（分）")
    execution_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True, comment="执行率，如 0.8567")
    snapshot_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="完整快照 JSON（含分配明细等）")

    # 关系
    budget: Mapped["Budget"] = relationship("Budget", back_populates="snapshots")
