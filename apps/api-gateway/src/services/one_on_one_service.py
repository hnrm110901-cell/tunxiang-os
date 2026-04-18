"""
1-on-1 面谈服务
- 模板管理 / 预约 / 开始 / 完成 / 我的面谈 / 团队覆盖率
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.one_on_one import OneOnOneFollowUp, OneOnOneMeeting, OneOnOneTemplate

logger = structlog.get_logger()

ALLOWED_CATEGORIES = {"performance", "career", "feedback", "onboarding", "pulse"}
ALLOWED_ROLES = {"initiator", "participant"}


class OneOnOneService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 模板 ──────────────────────────────────────
    async def create_template(
        self,
        name: str,
        topic_category: str,
        questions: List[Dict],
        is_default: bool = False,
        created_by: Optional[str] = None,
    ) -> OneOnOneTemplate:
        if topic_category not in ALLOWED_CATEGORIES:
            raise ValueError(f"非法话题分类: {topic_category}")
        tpl = OneOnOneTemplate(
            id=uuid.uuid4(),
            name=name,
            topic_category=topic_category,
            questions_json=questions,
            is_default=is_default,
            created_by=created_by,
        )
        self.db.add(tpl)
        await self.db.flush()
        return tpl

    # ── 预约 ──────────────────────────────────────
    async def schedule_meeting(
        self,
        initiator_id: str,
        participant_id: str,
        scheduled_at: datetime,
        template_id: Optional[uuid.UUID] = None,
        duration_min: int = 30,
        location: Optional[str] = None,
    ) -> OneOnOneMeeting:
        """校验双方时间冲突 ±duration_min 内不得有其它未取消会议"""
        window_start = scheduled_at - timedelta(minutes=duration_min)
        window_end = scheduled_at + timedelta(minutes=duration_min)
        stmt = select(OneOnOneMeeting).where(
            OneOnOneMeeting.status.in_(["scheduled", "confirmed", "in_progress"]),
            or_(
                OneOnOneMeeting.initiator_id.in_([initiator_id, participant_id]),
                OneOnOneMeeting.participant_id.in_([initiator_id, participant_id]),
            ),
            and_(
                OneOnOneMeeting.scheduled_at >= window_start,
                OneOnOneMeeting.scheduled_at <= window_end,
            ),
        )
        conflict = (await self.db.execute(stmt)).first()
        if conflict:
            raise ValueError("时间冲突：发起人或参与人在该时段已有未结束的 1-on-1 会议")

        meeting = OneOnOneMeeting(
            id=uuid.uuid4(),
            initiator_id=initiator_id,
            participant_id=participant_id,
            template_id=template_id,
            scheduled_at=scheduled_at,
            duration_min=duration_min,
            location=location,
            status="scheduled",
        )
        self.db.add(meeting)
        await self.db.flush()
        return meeting

    async def start_meeting(self, meeting_id: uuid.UUID) -> OneOnOneMeeting:
        m = await self._get_meeting(meeting_id)
        if m.status not in ("scheduled", "confirmed"):
            raise ValueError(f"会议状态不可开始: {m.status}")
        m.status = "in_progress"
        m.started_at = datetime.utcnow()
        await self.db.flush()
        return m

    async def complete_meeting(
        self,
        meeting_id: uuid.UUID,
        notes: str,
        action_items: Optional[List[Dict]] = None,
        auto_ai_summary: bool = True,
    ) -> OneOnOneMeeting:
        m = await self._get_meeting(meeting_id)
        if m.status not in ("in_progress", "scheduled", "confirmed"):
            raise ValueError(f"会议状态不可完成: {m.status}")

        m.status = "completed"
        m.ended_at = datetime.utcnow()
        m.notes = notes
        m.action_items_json = action_items or []

        # 自动创建跟进事项
        for ai in action_items or []:
            if not ai.get("item") or not ai.get("owner"):
                continue
            fu = OneOnOneFollowUp(
                id=uuid.uuid4(),
                meeting_id=m.id,
                action_item=ai["item"],
                owner_id=ai["owner"],
                due_date=ai.get("due"),
                status="pending",
            )
            self.db.add(fu)

        await self.db.flush()

        # AI 总结（容错）
        if auto_ai_summary:
            try:
                from .one_on_one_ai_service import OneOnOneAIService

                await OneOnOneAIService(self.db).summarize_meeting(m.id)
            except Exception as e:  # noqa: BLE001
                logger.warning("one_on_one_ai_summary_failed", meeting_id=str(m.id), error=str(e))

        return m

    # ── 查询 ──────────────────────────────────────
    async def list_my_meetings(
        self,
        user_id: str,
        role: str = "participant",
        status_filter: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[OneOnOneMeeting]:
        if role not in ALLOWED_ROLES:
            raise ValueError(f"role 必须是 {ALLOWED_ROLES}")
        col = OneOnOneMeeting.initiator_id if role == "initiator" else OneOnOneMeeting.participant_id
        stmt = select(OneOnOneMeeting).where(col == user_id).order_by(
            OneOnOneMeeting.scheduled_at.desc()
        ).limit(limit)
        if status_filter:
            stmt = stmt.where(OneOnOneMeeting.status.in_(status_filter))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_team_1on1_stats(self, manager_id: str, period_days: int = 30) -> Dict:
        """统计管理者最近 N 天内发起的 1-on-1 覆盖率"""
        since = datetime.utcnow() - timedelta(days=period_days)
        stmt = select(OneOnOneMeeting).where(
            OneOnOneMeeting.initiator_id == manager_id,
            OneOnOneMeeting.scheduled_at >= since,
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        unique_participants = {m.participant_id for m in rows}
        completed = sum(1 for m in rows if m.status == "completed")
        return {
            "manager_id": manager_id,
            "period_days": period_days,
            "total_meetings": len(rows),
            "completed_meetings": completed,
            "unique_participants": len(unique_participants),
            "completion_rate": round(completed / len(rows), 2) if rows else 0.0,
        }

    async def _get_meeting(self, meeting_id: uuid.UUID) -> OneOnOneMeeting:
        m = (
            await self.db.execute(select(OneOnOneMeeting).where(OneOnOneMeeting.id == meeting_id))
        ).scalar_one_or_none()
        if m is None:
            raise ValueError(f"会议不存在: {meeting_id}")
        return m
