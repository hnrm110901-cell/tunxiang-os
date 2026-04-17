"""
AgentMemory 模型 — Agent 持久化记忆（warm/cold 存储层）

三级存储模式：
  - hot  : Redis（TTL 1h，不在本表）
  - warm : 本表 level='warm'，保留 7 天
  - cold : 本表 level='cold'，归档永久保留

key 维度：(agent_id, session_id, key) 唯一定位一条记忆
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from .base import Base


class AgentMemory(Base):
    """Agent 记忆持久层（Redis 未命中时的 warm/cold 存储）"""

    __tablename__ = "agent_memories"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    agent_id = Column(String(64), nullable=False, index=True, comment="Agent 类型，如 schedule/inventory")
    session_id = Column(String(64), nullable=False, index=True, comment="会话ID，跨请求追踪")
    key = Column(String(128), nullable=False, comment="记忆键名")
    value_json = Column(JSONB, nullable=False, default=dict, comment="记忆值（任意 JSON 结构）")

    level = Column(String(16), nullable=False, default="warm", comment="存储层级：warm | cold")
    expires_at = Column(DateTime, nullable=True, comment="过期时间（cold 为空，warm 通常 7 天）")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("agent_id", "session_id", "key", name="uq_agent_memory_key"),
        Index("idx_agent_memory_expires", "expires_at"),
    )
