"""AgentMessage — Multi-Agent 协调消息模型

支持 Agent 间 request/response/notification/delegation 四种消息类型，
以及会话线程（correlation_id + parent_message_id）和优先级排序。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentMessage(TenantBase):
    """Agent 间协调消息表"""

    __tablename__ = "agent_messages"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="可选的会话范围 ID",
    )
    from_agent_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="发送方 Agent ID",
    )
    to_agent_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="接收方 Agent ID（NULL 表示广播）",
    )
    message_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="消息类型：request / response / notification / delegation",
    )
    action: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="请求执行的动作",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'::jsonb", comment="消息负载",
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=50, server_default="50", comment="优先级（越高越先处理）",
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="'pending'",
        comment="状态：pending / delivered / processed / failed / expired",
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 ID（串联 request↔response）",
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="父消息 ID（会话线程）",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理完成时间",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="消息过期时间",
    )

    __table_args__ = (
        Index("idx_agent_messages_to", "tenant_id", "to_agent_id", "status"),
        Index(
            "idx_agent_messages_session",
            "tenant_id", "session_id",
            postgresql_where="session_id IS NOT NULL",
        ),
        Index(
            "idx_agent_messages_correlation",
            "correlation_id",
            postgresql_where="correlation_id IS NOT NULL",
        ),
    )
