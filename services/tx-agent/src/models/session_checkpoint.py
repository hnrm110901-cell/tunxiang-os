"""Session Checkpoint 断点记录 — 支持 Agent 任务暂停、人工审核和断点恢复"""
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class SessionCheckpoint(TenantBase):
    """Session 断点 — 记录暂停原因、上下文和恢复信息"""

    __tablename__ = "session_checkpoints"

    # 关联 SessionRun
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_runs.id"),
        nullable=False,
        index=True,
        comment="关联的 SessionRun ID",
    )

    # 断点位置
    step_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="暂停在哪个步骤",
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="暂停时的 Agent",
    )

    # 暂停原因
    reason: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="暂停原因：pause/error/human_review/risk_approval",
    )
    reason_detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="详细原因",
    )

    # 断点数据
    checkpoint_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="断点上下文（恢复时需要的数据）",
    )
    pending_action: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="等待人工确认的动作描述",
    )

    # 解决信息
    resolution: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="解决方式：approved/rejected/skipped/auto_resolved",
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="解决者",
    )
    resolved_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解决时间",
    )
    resolved_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="解决意见",
    )

    # 恢复时间
    resumed_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Session 恢复时间",
    )
