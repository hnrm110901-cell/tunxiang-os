"""Session Run 运行实例 — Agent 任务执行的持久化会话记录，支持断点恢复"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class SessionRun(TenantBase):
    """Agent 任务运行实例 — 记录每次 AgentOrchestrator 调用的完整生命周期"""

    __tablename__ = "session_runs"

    # 可读的 session ID，如 "SR-20260412-abc123"
    session_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="可读的 session ID",
    )

    # 关联的 Agent 模板
    agent_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联的 Agent 模板 ID",
    )
    agent_template_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="冗余存储模板名（查询方便）",
    )

    # 门店
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="门店 ID",
    )

    # 触发信息
    trigger_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="触发方式：event/manual/scheduled/api",
    )
    trigger_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="触发数据（事件内容/用户指令等）",
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="created",
        comment="状态：created/running/paused/completed/failed/cancelled",
    )

    # 执行计划
    plan_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="关联的 ExecutionPlan.plan_id",
    )
    plan_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="ExecutionPlan 快照",
    )

    # 结果
    result_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="最终结果",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="失败原因",
    )

    # 进度统计
    total_steps: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="总步骤数",
    )
    completed_steps: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="已完成步骤数",
    )
    failed_steps: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="失败步骤数",
    )

    # 资源消耗
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="消耗的 token 总数",
    )
    total_cost_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="费用（分）",
    )

    # 时间
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始时间",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="结束时间",
    )

    __table_args__ = (
        Index("ix_session_run_status", "status"),
        Index("ix_session_run_store_time", "store_id", "started_at"),
    )
