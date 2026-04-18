"""
脉搏调研完整模型 — PulseSurveyTemplate / PulseSurveyInstance / PulseSurveyResponse
注：Wave 4 已有简版 pulse_surveys（单次打卡用），此处新建完整的模板/实例/作答三表。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class PulseSurveyTemplate(Base, TimestampMixin):
    """脉搏调研问卷模板"""

    __tablename__ = "pulse_survey_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    frequency = Column(String(20), nullable=False, default="monthly")  # weekly/biweekly/monthly/ad_hoc
    questions_json = Column(JSONB, nullable=False, default=list)
    # 结构: [{"id": 1, "type": "rating|text|multi_choice", "text": "...", "options": [...], "required": true}]
    target_scope = Column(String(20), nullable=False, default="all")  # all/store/role
    target_filter_json = Column(JSONB, nullable=True)  # {store_ids:[], roles:[]}
    is_active = Column(Boolean, default=True, nullable=False)
    allow_anonymous = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(50), nullable=True)


class PulseSurveyInstance(Base, TimestampMixin):
    """一次脉搏调研下发实例"""

    __tablename__ = "pulse_survey_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("pulse_survey_templates.id"), nullable=False, index=True)
    store_id = Column(String(50), nullable=True, index=True)
    scheduled_date = Column(Date, nullable=False, index=True)
    target_employee_ids_json = Column(JSONB, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="scheduled", index=True)
    # scheduled/sent/collecting/completed
    response_deadline = Column(DateTime, nullable=True)
    sent_count = Column(Integer, default=0)
    response_count = Column(Integer, default=0)
    summary_json = Column(JSONB, nullable=True)  # 聚合结果缓存


class PulseSurveyResponse(Base, TimestampMixin):
    """脉搏调研作答"""

    __tablename__ = "pulse_survey_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), ForeignKey("pulse_survey_instances.id"), nullable=False, index=True)
    employee_id = Column(String(50), nullable=True, index=True)  # 匿名时可为空
    employee_hash = Column(String(64), nullable=True, index=True)  # 匿名但去重用
    is_anonymous = Column(Boolean, default=False, nullable=False)
    responses_json = Column(JSONB, nullable=False, default=list)
    # 结构: [{"question_id": 1, "answer": "4"}, ...]
    sentiment_score = Column(Numeric(4, 2), nullable=True)  # -1.0 ~ 1.0
    sentiment_label = Column(String(20), nullable=True)  # positive/neutral/negative
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
