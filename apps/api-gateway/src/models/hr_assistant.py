"""
HR 数字人助手 — 会话与消息模型

hr_conversations  员工会话主表
hr_messages       每条消息（user/assistant/system/tool）
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


class HRConversation(Base, TimestampMixin):
    """员工与 HR 助手的会话主体"""

    __tablename__ = "hr_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    last_active_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)  # active | closed
    message_count = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    feedback_score = Column(Integer, nullable=True)      # 好/差评 1 or -1
    feedback_reason = Column(String(500), nullable=True)

    messages = relationship(
        "HRMessage", back_populates="conversation",
        cascade="all, delete-orphan", order_by="HRMessage.occurred_at",
    )


class HRMessage(Base, TimestampMixin):
    """单条对话消息 —— 含 tool_calls 审计"""

    __tablename__ = "hr_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hr_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = Column(String(20), nullable=False)  # user | assistant | system | tool
    content = Column(Text, nullable=False)
    tool_calls_json = Column(JSONB, nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cost_fen = Column(Integer, nullable=True)   # 成本按分存储
    occurred_at = Column(DateTime, nullable=False, index=True)

    conversation = relationship("HRConversation", back_populates="messages")
