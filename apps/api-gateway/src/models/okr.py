"""
OKR 目标管理模型 — Objective / KeyResult / OKRUpdate / OKRAlignment
对标 i人事 OKR 模块：支持个人/团队/公司三级目标 + KR 打卡 + 目标对齐
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class Objective(Base, TimestampMixin):
    """目标 Objective"""

    __tablename__ = "okr_objectives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(String(50), nullable=False, index=True)  # 员工 id / 团队 id / 公司 id
    owner_type = Column(String(20), nullable=False, default="personal", index=True)  # personal/team/company
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    period = Column(String(20), nullable=False, index=True)  # 2026Q1 / 2026Q2 / 2026H1 / 2026
    parent_objective_id = Column(UUID(as_uuid=True), ForeignKey("okr_objectives.id"), nullable=True, index=True)
    target_value = Column(Numeric(18, 2), nullable=True)
    actual_value = Column(Numeric(18, 2), nullable=True)
    weight = Column(Integer, default=100)  # 0-100，相对权重
    status = Column(String(20), nullable=False, default="draft", index=True)  # draft/active/completed/abandoned
    progress_pct = Column(Numeric(5, 2), default=0)  # 0-100
    health = Column(String(10), default="green", index=True)  # green/yellow/red
    store_id = Column(String(50), nullable=True, index=True)


class KeyResult(Base, TimestampMixin):
    """关键结果 KR"""

    __tablename__ = "okr_key_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    objective_id = Column(UUID(as_uuid=True), ForeignKey("okr_objectives.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    metric_type = Column(String(20), nullable=False, default="numeric")  # numeric/percentage/boolean/milestone
    start_value = Column(Numeric(18, 2), default=0)
    target_value = Column(Numeric(18, 2), nullable=False)
    current_value = Column(Numeric(18, 2), default=0)
    unit = Column(String(20), nullable=True)  # 元/%/单/次
    weight = Column(Integer, default=100)  # 0-100
    owner_id = Column(String(50), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    progress_pct = Column(Numeric(5, 2), default=0)


class OKRUpdate(Base, TimestampMixin):
    """KR 打卡更新日志"""

    __tablename__ = "okr_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_result_id = Column(UUID(as_uuid=True), ForeignKey("okr_key_results.id"), nullable=False, index=True)
    value = Column(Numeric(18, 2), nullable=False)
    comment = Column(Text, nullable=True)
    evidence_url = Column(String(500), nullable=True)
    updated_by = Column(String(50), nullable=False, index=True)
    updated_at_ts = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class OKRAlignment(Base, TimestampMixin):
    """目标对齐关系（父→子）"""

    __tablename__ = "okr_alignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_objective_id = Column(UUID(as_uuid=True), ForeignKey("okr_objectives.id"), nullable=False, index=True)
    child_objective_id = Column(UUID(as_uuid=True), ForeignKey("okr_objectives.id"), nullable=False, index=True)
    alignment_type = Column(String(20), nullable=False, default="contribute_to")  # contribute_to/support/depend_on
    notes = Column(Text, nullable=True)
    extra_json = Column(JSONB, nullable=True)
