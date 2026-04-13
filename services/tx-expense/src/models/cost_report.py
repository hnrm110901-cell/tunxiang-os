"""
成本归集 ORM 模型
包含：DailyCostReport（每日成本归集日报）、CostAttributionItem（成本归集明细）

设计说明：
- 所有金额字段单位为分(fen)，BigInteger 存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离（tenant_id + is_deleted 由基类提供）
- 与 v243 迁移文件表结构完全对应
- DailyCostReport 按 (tenant_id, store_id, report_date) 唯一约束
- cost_type: food/labor/rent/utility/other
- data_status: pending/complete/manual_adjusted
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────────────────────────────────────
# DailyCostReport — 每日成本归集日报
# ─────────────────────────────────────────────────────────────────────────────

class DailyCostReport(TenantBase):
    """
    每日成本归集日报。
    营收来自 tx-ops POS 日结，成本来自当日已审批费控申请。
    Worker 每晚 23:30 运行，计算成本率和毛利率后写入本表。

    data_status 生命周期：
        pending         — Worker 尚未处理（或处理中）
        complete        — Worker 已完成归集计算
        manual_adjusted — 人工调整过数据
    """
    __tablename__ = "daily_cost_reports"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="门店ID"
    )
    report_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="日报日期"
    )

    # ── 营收数据（来自POS）────────────────────────────────────────────────
    total_revenue_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="当日营收（分）",
    )
    table_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="桌次",
    )
    customer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="客数",
    )

    # ── 成本数据（来自费控）──────────────────────────────────────────────
    food_cost_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="食材成本（分）",
    )
    labor_cost_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="人力成本（分）",
    )
    other_cost_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="其他费用（分）",
    )
    total_cost_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="总成本（分）",
    )

    # ── 计算指标────────────────────────────────────────────────────────
    food_cost_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4), nullable=True,
        comment="食材成本率 = food_cost_fen / total_revenue_fen",
    )
    labor_cost_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4), nullable=True,
        comment="人力成本率 = labor_cost_fen / total_revenue_fen",
    )
    gross_margin_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4), nullable=True,
        comment="毛利率 = (total_revenue_fen - total_cost_fen) / total_revenue_fen",
    )

    # ── 元数据──────────────────────────────────────────────────────────
    pos_data_source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="POS数据来源：pinzhi/aoqiwei/meituan",
    )
    data_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending",
        comment="数据状态：pending/complete/manual_adjusted",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="备注"
    )

    # ── 关联──────────────────────────────────────────────────────────
    attribution_items: Mapped[List["CostAttributionItem"]] = relationship(
        "CostAttributionItem",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def compute_rates(self) -> None:
        """就地计算成本率和毛利率（营收为0时保持 None，避免除零）。"""
        if self.total_revenue_fen and self.total_revenue_fen > 0:
            rev = self.total_revenue_fen
            self.food_cost_rate = Decimal(self.food_cost_fen) / Decimal(rev)
            self.labor_cost_rate = Decimal(self.labor_cost_fen) / Decimal(rev)
            self.gross_margin_rate = Decimal(rev - self.total_cost_fen) / Decimal(rev)
        else:
            self.food_cost_rate = None
            self.labor_cost_rate = None
            self.gross_margin_rate = None


# ─────────────────────────────────────────────────────────────────────────────
# CostAttributionItem — 成本归集明细
# ─────────────────────────────────────────────────────────────────────────────

class CostAttributionItem(TenantBase):
    """
    成本归集明细。记录每一笔费控申请如何归集到门店成本日报。

    cost_type 枚举值：
        food    — 食材/原料成本
        labor   — 人力/薪资成本
        rent    — 租金
        utility — 水电气
        other   — 其他费用
    """
    __tablename__ = "cost_attribution_items"

    report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_cost_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联日报ID",
    )
    expense_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="费控申请ID",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="门店ID"
    )
    attribution_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="归集日期"
    )
    cost_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="成本类型：food/labor/rent/utility/other",
    )
    amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="金额（分）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="描述"
    )

    # ── 关联──────────────────────────────────────────────────────────
    report: Mapped[Optional["DailyCostReport"]] = relationship(
        "DailyCostReport",
        back_populates="attribution_items",
        lazy="select",
    )
