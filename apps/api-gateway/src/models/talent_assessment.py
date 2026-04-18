"""
九宫格人才盘点模型
- TalentAssessment: 人才盘点记录（业绩×潜力 → 九宫格 1..9）
- TalentPool: 人才池（高潜/继任/关键岗位/观察名单）
- SuccessionPlan: 关键岗位继任方案

九宫格 cell 公式:
    cell = (performance - 1) * 3 + potential
    x 轴 performance 1→3 (低→高) = 左→右
    y 轴 potential   1→3 (低→高) = 下→上
所以 cell=1 左下 (低绩低潜 / 观察清退), cell=9 右上 (高绩高潜 / 明星)
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, TimestampMixin


class TalentAssessment(Base, TimestampMixin):
    """人才盘点 — 一次盘点一条"""

    __tablename__ = "talent_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    assessor_id = Column(String(50), nullable=False, index=True)  # 盘点人
    assessment_date = Column(Date, nullable=False, index=True)

    performance_score = Column(Integer, nullable=False)  # 1-5 (将映射到 1-3 网格)
    potential_score = Column(Integer, nullable=False)  # 1-5
    nine_box_cell = Column(Integer, nullable=False, index=True)  # 1-9

    strengths = Column(Text, nullable=True)
    development_areas = Column(Text, nullable=True)
    career_path = Column(Text, nullable=True)
    ai_development_plan = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="draft", index=True)
    # draft | submitted | approved


class TalentPool(Base, TimestampMixin):
    """人才池"""

    __tablename__ = "talent_pools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    # high_potential | successor | key_position | watch_list
    pool_type = Column(String(30), nullable=False, index=True)
    target_position = Column(String(100), nullable=True)
    # ready_now | 1year | 2year
    readiness = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    notes = Column(Text, nullable=True)
    added_at = Column(DateTime, nullable=False, server_default=func.now())


class SuccessionPlan(Base, TimestampMixin):
    """关键岗位继任方案"""

    __tablename__ = "succession_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 岗位 ID（关联岗位字典或自由文本），暂用 String
    key_position_id = Column(String(100), nullable=False, index=True)
    current_holder_id = Column(String(50), ForeignKey("employees.id"), nullable=True)
    successor_id = Column(String(50), ForeignKey("employees.id"), nullable=True)
    readiness = Column(String(20), nullable=True)
    gap_analysis = Column(Text, nullable=True)
    development_plan = Column(Text, nullable=True)
    candidates_json = Column(JSONB, nullable=True)  # 候选人 top N 缓存
