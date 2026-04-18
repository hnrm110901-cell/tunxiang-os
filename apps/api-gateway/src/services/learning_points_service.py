"""
学习积分服务 — 发积分 / 排行榜 / 徽章检查
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.learning_path import (
    LearningAchievement,
    LearningPathEnrollment,
    LearningPoints,
)

logger = logging.getLogger(__name__)


# 事件 -> 默认积分
DEFAULT_POINTS = {
    "course_complete": 10,
    "exam_pass": 20,
    "quiz_pass": 5,
    "teach_others": 15,
    "path_complete": 50,
}


class LearningPointsService:
    """积分服务"""

    async def award(
        self,
        db: AsyncSession,
        *,
        employee_id: str,
        event_type: str,
        points: Optional[int] = None,
        source_id: Optional[str] = None,
        store_id: Optional[str] = None,
        awarded_by: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> str:
        """发积分"""
        value = points if points is not None else DEFAULT_POINTS.get(event_type, 0)
        rec = LearningPoints(
            id=uuid.uuid4(),
            employee_id=employee_id,
            store_id=store_id,
            event_type=event_type,
            points_value=int(value),
            source_id=source_id,
            awarded_by=awarded_by,
            remark=remark,
        )
        db.add(rec)
        await db.flush()
        logger.info("learning_points_awarded emp=%s evt=%s pts=%s", employee_id, event_type, value)
        return str(rec.id)

    async def get_leaderboard(
        self,
        db: AsyncSession,
        *,
        store_id: Optional[str] = None,
        period: str = "month",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """积分排行榜（按周期）"""
        now = datetime.utcnow()
        if period == "week":
            since = now - timedelta(days=7)
        elif period == "quarter":
            since = now - timedelta(days=90)
        elif period == "year":
            since = now - timedelta(days=365)
        else:
            since = now - timedelta(days=30)

        q = select(
            LearningPoints.employee_id,
            func.sum(LearningPoints.points_value).label("total_points"),
            func.count(LearningPoints.id).label("event_count"),
        ).where(LearningPoints.awarded_at >= since)
        if store_id:
            q = q.where(LearningPoints.store_id == store_id)
        q = q.group_by(LearningPoints.employee_id).order_by(
            func.sum(LearningPoints.points_value).desc()
        ).limit(limit)

        rows = (await db.execute(q)).all()
        return [
            {
                "rank": idx + 1,
                "employee_id": r.employee_id,
                "total_points": int(r.total_points or 0),
                "event_count": int(r.event_count or 0),
            }
            for idx, r in enumerate(rows)
        ]

    async def get_my_points(
        self, db: AsyncSession, *, employee_id: str, recent: int = 10
    ) -> Dict[str, Any]:
        """我的积分总览 + 近期事件"""
        total = (
            await db.execute(
                select(func.sum(LearningPoints.points_value)).where(
                    LearningPoints.employee_id == employee_id
                )
            )
        ).scalar() or 0
        rows = (
            await db.execute(
                select(LearningPoints)
                .where(LearningPoints.employee_id == employee_id)
                .order_by(LearningPoints.awarded_at.desc())
                .limit(recent)
            )
        ).scalars().all()
        return {
            "employee_id": employee_id,
            "total_points": int(total),
            "recent_events": [
                {
                    "event_type": r.event_type,
                    "points_value": r.points_value,
                    "source_id": r.source_id,
                    "awarded_at": r.awarded_at.isoformat() if r.awarded_at else None,
                    "remark": r.remark,
                }
                for r in rows
            ],
        }

    # ─── 徽章 ─────────────────────────────────────
    BADGES = {
        "learning_master": {"name": "学习达人", "paths_completed": 3},
        "exam_ace": {"name": "考试王者", "min_points": 200},
    }

    async def check_badge_eligibility(
        self, db: AsyncSession, *, employee_id: str
    ) -> List[Dict[str, Any]]:
        """检查并颁发徽章"""
        awarded: List[Dict[str, Any]] = []

        # 已拿到的徽章
        existing = {
            r.badge_code
            for r in (
                await db.execute(
                    select(LearningAchievement).where(
                        LearningAchievement.employee_id == employee_id
                    )
                )
            ).scalars().all()
        }

        # 学习达人：完成 3 条路径
        if "learning_master" not in existing:
            cnt = (
                await db.execute(
                    select(func.count(LearningPathEnrollment.id)).where(
                        LearningPathEnrollment.employee_id == employee_id,
                        LearningPathEnrollment.status == "completed",
                    )
                )
            ).scalar() or 0
            if cnt >= 3:
                badge = LearningAchievement(
                    id=uuid.uuid4(),
                    employee_id=employee_id,
                    badge_code="learning_master",
                    badge_name=self.BADGES["learning_master"]["name"],
                )
                db.add(badge)
                awarded.append({"code": "learning_master", "name": badge.badge_name})

        # 考试王者：累计 >=200 积分
        if "exam_ace" not in existing:
            total = (
                await db.execute(
                    select(func.sum(LearningPoints.points_value)).where(
                        LearningPoints.employee_id == employee_id
                    )
                )
            ).scalar() or 0
            if int(total) >= 200:
                badge = LearningAchievement(
                    id=uuid.uuid4(),
                    employee_id=employee_id,
                    badge_code="exam_ace",
                    badge_name=self.BADGES["exam_ace"]["name"],
                )
                db.add(badge)
                awarded.append({"code": "exam_ace", "name": badge.badge_name})

        if awarded:
            await db.flush()
        return awarded


learning_points_service = LearningPointsService()
