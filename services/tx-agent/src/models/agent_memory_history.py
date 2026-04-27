"""AgentMemoryHistory — 记忆变更审计日志（不可删除）"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _AuditBase(DeclarativeBase):
    """审计表基类 — 无 is_deleted，记录不可删除"""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentMemoryHistory(_AuditBase):
    """记忆变更审计日志 — 不可变，无 is_deleted / updated_at"""

    __tablename__ = "agent_memory_history"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="被变更的记忆 ID",
    )
    memory_table: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="来源表：agent_memories / agent_episodes / agent_procedures",
    )
    event_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="变更类型：ADD / UPDATE / DELETE / DECAY / MERGE",
    )
    old_value: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="变更前快照",
    )
    new_value: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="变更后快照",
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="变更原因",
    )
    actor: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="操作者：agent / system / user",
    )
