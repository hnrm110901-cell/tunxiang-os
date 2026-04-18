"""
学习路径/积分/成就模型 — 对标 i人事 E-learning 学习地图 + 积分 + 徽章
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class LearningPath(Base, TimestampMixin):
    """学习地图 / 学习路径"""

    __tablename__ = "learning_paths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    target_position_id = Column(String(100), nullable=True, index=True)  # 岗位编码
    required_courses_json = Column(JSONB, nullable=False, default=list)
    # 结构: [{"course_id": "...", "order": 1, "is_mandatory": true, "prerequisite_ids": []}]
    estimated_hours = Column(Integer, default=0)
    created_by = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class LearningPathEnrollment(Base, TimestampMixin):
    """员工学习路径注册"""

    __tablename__ = "learning_path_enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id"), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    progress_pct = Column(Integer, default=0)  # 0-100
    current_course_id = Column(String(100), nullable=True)
    completed_courses_json = Column(JSONB, nullable=False, default=list)  # ["course_id_1",...]
    status = Column(String(20), nullable=False, default="not_started", index=True)
    # not_started/in_progress/completed/abandoned


class LearningPoints(Base, TimestampMixin):
    """学习积分流水"""

    __tablename__ = "learning_points"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), nullable=False, index=True)
    store_id = Column(String(50), nullable=True, index=True)
    event_type = Column(String(30), nullable=False, index=True)
    # course_complete/exam_pass/quiz_pass/teach_others/path_complete
    points_value = Column(Integer, nullable=False, default=0)
    source_id = Column(String(100), nullable=True)  # 关联 course_id/exam_id/path_id
    awarded_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    awarded_by = Column(String(50), nullable=True)
    remark = Column(String(200), nullable=True)


class LearningAchievement(Base, TimestampMixin):
    """学习徽章 / 成就"""

    __tablename__ = "learning_achievements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), nullable=False, index=True)
    badge_code = Column(String(50), nullable=False, index=True)
    badge_name = Column(String(100), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source_path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id"), nullable=True)
