"""Session Event 事件记录 — 记录 Session 执行过程中每个步骤的详细事件"""
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class SessionEvent(TenantBase):
    """Session 事件 — 记录每个执行步骤的输入、输出、推理过程和资源消耗"""

    __tablename__ = "session_events"

    # 关联 SessionRun
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_runs.id"),
        nullable=False,
        index=True,
        comment="关联的 SessionRun ID",
    )

    # 事件序号（同一 session 内递增）
    sequence_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="事件序号（同一 session 内递增）",
    )

    # 事件类型
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="事件类型：step_started/step_completed/step_failed/"
                "checkpoint_created/session_paused/session_resumed/"
                "tool_called/constraint_checked",
    )

    # 步骤信息
    step_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="关联的执行步骤 ID",
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="执行的 Agent ID",
    )
    action: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="执行的 action",
    )

    # 输入/输出
    input_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="输入参数",
    )
    output_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="输出结果",
    )
    reasoning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="推理过程",
    )

    # 资源消耗
    tokens_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="使用的 token 数",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="耗时（毫秒）",
    )

    # 推理层
    inference_layer: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="推理层：edge/cloud",
    )

    __table_args__ = (
        Index("ix_session_event_session_seq", "session_id", "sequence_no"),
    )
