"""
1-on-1 面谈模型
- OneOnOneTemplate: 面谈模板（话题分类 + 问题列表）
- OneOnOneMeeting: 面谈会议（预约-开始-完成 状态机）
- OneOnOneFollowUp: 后续跟进事项
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class OneOnOneTemplate(Base, TimestampMixin):
    """面谈模板"""

    __tablename__ = "one_on_one_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    # performance | career | feedback | onboarding | pulse
    topic_category = Column(String(30), nullable=False, index=True)
    questions_json = Column(JSONB, nullable=False, default=list)  # [{"q":"...","hint":"..."}]
    is_default = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(50), nullable=True)


class OneOnOneMeeting(Base, TimestampMixin):
    """1-on-1 面谈"""

    __tablename__ = "one_on_one_meetings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    initiator_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    participant_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("one_on_one_templates.id"), nullable=True)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    duration_min = Column(Integer, nullable=False, default=30)
    location = Column(String(200), nullable=True)
    # scheduled | confirmed | in_progress | completed | cancelled
    status = Column(String(20), nullable=False, default="scheduled", index=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    action_items_json = Column(JSONB, nullable=True)  # [{"item":"","owner":"","due":"YYYY-MM-DD"}]
    follow_up_date = Column(Date, nullable=True)


class OneOnOneFollowUp(Base, TimestampMixin):
    """面谈跟进事项"""

    __tablename__ = "one_on_one_follow_ups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(
        UUID(as_uuid=True), ForeignKey("one_on_one_meetings.id"), nullable=False, index=True
    )
    action_item = Column(Text, nullable=False)
    owner_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    due_date = Column(Date, nullable=True)
    # pending | done | overdue
    status = Column(String(20), nullable=False, default="pending", index=True)
    completed_at = Column(DateTime, nullable=True)
