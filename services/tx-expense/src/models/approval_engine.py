"""
审批引擎 ORM 模型
包含：ApprovalRoutingRule（路由规则）、ApprovalInstance（审批实例）、ApprovalNode（审批节点）

设计原则：
- 审批链在实例创建时固化为 routing_snapshot JSON，即使后续规则修改也不影响进行中的审批
- 所有涉及资金流出的操作 100% 保留人工审批节点，Agent 不可绕过
- amount_min / amount_max 单位均为分(fen)，-1 表示无上限
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase
from .expense_enums import ApprovalAction, ApprovalNodeStatus, ApprovalRoutingType


# ─────────────────────────────────────────────────────────────────────────────
# ApprovalRoutingRule — 审批路由规则配置
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalRoutingRule(TenantBase):
    """
    审批路由规则配置
    金额路由规则示例：
      - amount_min=0,       amount_max=49999  → approver_role=store_manager（<500元）
      - amount_min=50000,   amount_max=199999 → approver_role=region_manager（500~2000元）
      - amount_min=200000,  amount_max=-1     → approver_role=hq_finance（>=2000元，-1=无上限）
    scenario_code 为 NULL 表示通用规则，适用于所有场景。
    """
    __tablename__ = "approval_routing_rules"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="所属品牌ID（路由规则按品牌隔离）"
    )
    scenario_code: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True,
        comment="适用场景代码，NULL 表示通用规则（参见 ExpenseScenarioCode 枚举）"
    )
    routing_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ApprovalRoutingType.AMOUNT_BASED.value,
        comment="路由类型，参见 ApprovalRoutingType 枚举"
    )
    amount_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="金额下限（含），单位：分(fen)"
    )
    amount_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1,
        comment="金额上限（含），单位：分(fen)，-1 表示无上限"
    )
    approver_role: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="审批人角色标识，如 store_manager / region_manager / hq_finance"
    )
    approver_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="需要几位该角色审批人通过（合同类场景用于双签）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ApprovalInstance — 审批实例（1申请:1实例）
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalInstance(TenantBase):
    """
    审批实例
    每个费用申请对应一个审批实例，实例创建时将当前有效的路由规则
    固化为 routing_snapshot JSON 快照，确保审批链不受后续规则变更影响。
    """
    __tablename__ = "approval_instances"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_approval_instance_application"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="关联费用申请ID（1:1）"
    )
    current_node_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="当前待处理节点的0-based索引"
    )
    total_nodes: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="审批节点总数（由 routing_snapshot 决定，创建时固化）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalNodeStatus.PENDING.value,
        index=True,
        comment="整体审批状态，参见 ApprovalNodeStatus 枚举"
    )
    routing_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment=(
            "创建时固化的完整审批链快照，不受后续规则变更影响。"
            "格式: [{\"node_index\": 0, \"approver_role\": \"store_manager\", "
            "\"approver_count\": 1, \"routing_type\": \"amount_based\"}]"
        )
    )

    # 关系
    application: Mapped["ExpenseApplication"] = relationship(
        "ExpenseApplication",
        foreign_keys=[application_id],
        lazy="select",
    )
    nodes: Mapped[List["ApprovalNode"]] = relationship(
        "ApprovalNode",
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="ApprovalNode.node_index",
        lazy="select",
    )


# 延迟导入（避免循环引用）
from .expense_application import ExpenseApplication  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# ApprovalNode — 审批节点
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalNode(TenantBase):
    """
    审批节点
    审批实例下的每个人工审批节点。
    action 和 acted_at 仅在审批人操作后填充。
    Agent 不可直接设置节点状态为 approved/rejected，必须通过人工操作。
    """
    __tablename__ = "approval_nodes"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属审批实例ID"
    )
    node_index: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="节点在审批链中的0-based顺序索引"
    )
    approver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="审批人员工ID"
    )
    approver_role: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="审批人角色标识，如 store_manager / region_manager / hq_finance"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalNodeStatus.PENDING.value,
        index=True,
        comment="节点状态，参见 ApprovalNodeStatus 枚举"
    )
    action: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="审批动作，参见 ApprovalAction 枚举（approve/reject/transfer/request_revision）"
    )
    comment: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="审批意见/驳回原因"
    )
    acted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批操作时间"
    )

    # 关系
    instance: Mapped["ApprovalInstance"] = relationship(
        "ApprovalInstance", back_populates="nodes", foreign_keys=[instance_id]
    )
