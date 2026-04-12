"""AgentMemory — Agent 跨会话记忆持久化模型"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentMemory(TenantBase):
    """Agent 跨会话记忆 — 存储洞察、规则、偏好等可复用知识"""

    __tablename__ = "agent_memories"

    agent_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Agent ID",
    )
    memory_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="记忆类型：finding / insight / preference / learned_rule",
    )
    memory_key: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="可搜索的记忆键",
    )
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="记忆内容（JSON）",
    )
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0, server_default="1.0", comment="置信度 0-1",
    )

    # 可选范围限定
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="门店范围（可选）",
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="创建此记忆的会话 ID",
    )
    embedding_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="向量存储引用 ID（用于相似度搜索）",
    )

    # 访问统计
    access_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="访问次数",
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后访问时间",
    )

    # 过期
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="过期时间（可选 TTL）",
    )
