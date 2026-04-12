"""
合同台账 ORM 模型
包含：Contract（合同主表）、ContractPayment（付款计划）、ContractAlert（合同预警记录）

设计说明：
- 所有金额字段单位为分(fen)，BigInteger 存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离（tenant_id + is_deleted 由基类提供）
- 与 v241 迁移文件表结构完全对应
- ContractAlert 幂等创建机制：按 (tenant_id, contract_id, alert_type, 日期) 去重
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


# ─────────────────────────────────────────────────────────────────────────────
# Contract — 合同主表
# ─────────────────────────────────────────────────────────────────────────────

class Contract(TenantBase):
    """
    合同主表
    覆盖门店租约、设备采购、服务外包、劳务等各类合同。
    total_amount / paid_amount 单位均为分(fen)。
    """
    __tablename__ = "contracts"

    contract_no: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="合同编号（租户内唯一，结合 tenant_id 唯一约束）"
    )
    contract_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="合同名称"
    )
    contract_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="合同类型：rental/equipment/service/labor/other"
    )

    counterparty_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="乙方/甲方名称"
    )
    counterparty_contact: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="对方联系人"
    )

    total_amount: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, comment="合同总金额（分）"
    )
    paid_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="已付金额（分）"
    )

    start_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="合同开始日期"
    )
    end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="合同结束日期"
    )

    auto_renew: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="是否自动续约"
    )
    renewal_notice_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30",
        comment="提前N天提醒续签"
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active",
        comment="合同状态：draft/active/expired/terminated"
    )

    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="关联门店ID"
    )
    responsible_person: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="合同负责人员工ID"
    )

    file_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="合同附件URL"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="备注"
    )

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="创建人"
    )

    # 关系
    payments: Mapped[List["ContractPayment"]] = relationship(
        "ContractPayment",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="select",
    )
    alerts: Mapped[List["ContractAlert"]] = relationship(
        "ContractAlert",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ContractPayment — 付款计划
# ─────────────────────────────────────────────────────────────────────────────

class ContractPayment(TenantBase):
    """
    合同付款计划
    每条记录对应合同的一个付款期次（如季度租金、年度服务费分期等）。
    planned_amount / actual_amount 单位均为分(fen)。
    """
    __tablename__ = "contract_payments"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属合同ID",
    )

    period_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="期次名称，如'2026年Q1'"
    )
    due_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="计划付款日期"
    )

    planned_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="计划付款金额（分）"
    )
    actual_amount: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, comment="实际付款金额（分）"
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending",
        comment="付款状态：pending/paid/overdue/cancelled"
    )

    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际付款时间"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="备注"
    )

    # 关系
    contract: Mapped["Contract"] = relationship(
        "Contract", back_populates="payments"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ContractAlert — 合同预警记录
# ─────────────────────────────────────────────────────────────────────────────

class ContractAlert(TenantBase):
    """
    合同预警记录
    幂等创建：同一合同同一天同类型预警只创建一条，避免重复推送。
    is_deleted 和 updated_at 由 TenantBase 提供（ContractAlert 不用 is_deleted，但保留基类字段）。
    """
    __tablename__ = "contract_alerts"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属合同ID",
    )

    alert_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="预警类型：expiry/payment_due/auto_renew/overspend"
    )
    alert_days_before: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="提前多少天触发预警"
    )
    message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="预警消息内容"
    )

    is_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="是否已推送"
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="推送时间"
    )

    # 关系
    contract: Mapped["Contract"] = relationship(
        "Contract", back_populates="alerts"
    )
