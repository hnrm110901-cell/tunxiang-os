"""营销审批流数据模型

表：
  approval_workflows  — 审批流模板（定义触发条件与审批步骤）
  approval_requests   — 审批单（每次触发审批产生一条记录）

状态机（approval_requests.status）:
  pending -> approved | rejected | expired | cancelled

金额单位：分(fen)
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ApprovalWorkflow(TenantBase):
    """审批流模板

    定义哪些营销操作需要走审批、走几级审批、超时如何处理。

    trigger_conditions 示例：
    {
        "type": "campaign_activation",
        "conditions": [
            {"field": "max_discount_fen", "op": "gt", "value": 5000}
        ]
    }

    steps 示例：
    [
        {"step": 1, "role": "store_manager",    "timeout_hours": 24, "auto_approve_on_timeout": False},
        {"step": 2, "role": "regional_manager", "timeout_hours": 48, "auto_approve_on_timeout": True},
    ]
    """
    __tablename__ = "approval_workflows"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="审批流名称，如：大额优惠审批流",
    )

    # 触发条件（JSONB）— AND 逻辑，所有条件同时满足才触发
    trigger_conditions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="触发条件: {type, conditions:[{field, op, value}]}",
    )

    # 审批步骤列表（JSONB）— 按 step 顺序执行
    steps: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="审批步骤列表: [{step, role, timeout_hours, auto_approve_on_timeout}]",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否启用",
    )

    # 多个工作流同时匹配时，取 priority 最高（值最大）的执行
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="优先级（值越大越优先），多个工作流匹配时取最高优先级",
    )

    __table_args__ = (
        Index("idx_approval_workflows_tenant_active", "tenant_id", "is_active"),
        Index("idx_approval_workflows_tenant_priority", "tenant_id", "priority"),
        {"comment": "审批流模板表"},
    )


class ApprovalRequest(TenantBase):
    """审批单

    状态机: pending -> approved | rejected | expired | cancelled
    """
    __tablename__ = "approval_requests"

    # 关联审批流模板
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="所属审批流模板",
    )

    # 审批对象
    object_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="campaign | journey | referral_campaign | stored_value_plan",
    )
    object_id: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="被审批对象的 ID",
    )
    # 冗余存储关键摘要，避免审批页反复关联查询
    object_summary: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="审批内容摘要 JSONB，如 {name, type, max_discount_fen}",
    )

    # 申请人信息（冗余，避免关联 tx-org）
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="申请人员工 ID",
    )
    requester_name: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="申请人姓名（冗余存储）",
    )

    # 审批状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending | approved | rejected | cancelled | expired",
    )
    current_step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="当前审批步骤编号（从1开始）",
    )

    # 审批历史（JSONB），追加写入，不更新历史条目
    # 格式：[{"step": 1, "approver_id": "uuid", "action": "approved", "comment": "...", "at": "ISO8601"}]
    approval_history: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="审批操作历史列表 JSONB",
    )

    reject_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="拒绝原因（rejected 时填入）",
    )

    # 关键时间戳
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="全部审批通过时间",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="当前步骤超时时间（now + step.timeout_hours）",
    )

    __table_args__ = (
        Index("idx_approval_requests_tenant_status", "tenant_id", "status"),
        Index("idx_approval_requests_tenant_object", "tenant_id", "object_type", "object_id"),
        Index("idx_approval_requests_requester", "tenant_id", "requester_id"),
        Index("idx_approval_requests_expires", "tenant_id", "expires_at",
              postgresql_where="status = 'pending'"),
        {"comment": "审批单表"},
    )
