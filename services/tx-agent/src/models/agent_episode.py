"""AgentEpisode — Agent 情景记忆（门店运营关键事件片段）"""
import uuid
from datetime import date, datetime
from typing import List

from sqlalchemy import Boolean, Date, DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentEpisode(TenantBase):
    """Agent 情景记忆 — 记录异常/决策/事故/成功等关键事件片段"""

    __tablename__ = "agent_episodes"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店 ID",
    )
    episode_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="事件类型：anomaly / decision / incident / success",
    )
    episode_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="事件发生日期",
    )
    time_slot: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="时段：morning_prep / lunch_peak / afternoon_lull / dinner_peak / closing",
    )
    context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="事件发生时的完整上下文",
    )
    action_taken: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="采取的行动",
    )
    outcome: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="行动结果",
    )
    lesson: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="提炼的经验教训",
    )
    related_memories: Mapped[List[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True,
        comment="关联的 agent_memories ID 数组",
    )
