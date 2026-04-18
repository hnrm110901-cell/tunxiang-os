"""
学习路径服务 — 创建路径 / 员工注册 / 完成课程 / 推荐
核心约束：前置课程（prerequisite_ids）未完成不能开后续课
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.learning_path import LearningPath, LearningPathEnrollment
from src.services.learning_points_service import learning_points_service

logger = logging.getLogger(__name__)


class LearningPathService:
    """学习地图服务"""

    async def create_path(
        self,
        db: AsyncSession,
        *,
        code: str,
        name: str,
        target_position: Optional[str] = None,
        courses: Optional[List[Dict[str, Any]]] = None,
        description: Optional[str] = None,
        estimated_hours: int = 0,
        created_by: Optional[str] = None,
    ) -> str:
        """创建学习路径"""
        path = LearningPath(
            id=uuid.uuid4(),
            code=code,
            name=name,
            description=description,
            target_position_id=target_position,
            required_courses_json=courses or [],
            estimated_hours=estimated_hours,
            created_by=created_by,
        )
        db.add(path)
        await db.flush()
        return str(path.id)

    async def enroll(
        self, db: AsyncSession, *, path_id: str, employee_id: str
    ) -> str:
        """员工加入路径"""
        # 避免重复注册
        existing = (
            await db.execute(
                select(LearningPathEnrollment).where(
                    LearningPathEnrollment.path_id == path_id,
                    LearningPathEnrollment.employee_id == employee_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return str(existing.id)

        path = await db.get(LearningPath, uuid.UUID(path_id) if isinstance(path_id, str) else path_id)
        if not path:
            raise ValueError(f"LearningPath {path_id} not found")

        courses = sorted(path.required_courses_json or [], key=lambda c: c.get("order", 0))
        first_course = courses[0]["course_id"] if courses else None

        enrollment = LearningPathEnrollment(
            id=uuid.uuid4(),
            path_id=path.id,
            employee_id=employee_id,
            status="in_progress" if first_course else "not_started",
            progress_pct=0,
            current_course_id=first_course,
            completed_courses_json=[],
        )
        db.add(enrollment)
        await db.flush()
        return str(enrollment.id)

    async def get_progress(
        self, db: AsyncSession, *, employee_id: str, path_id: str
    ) -> Dict[str, Any]:
        """查询进度 + 下一门课"""
        enr = (
            await db.execute(
                select(LearningPathEnrollment).where(
                    LearningPathEnrollment.path_id == path_id,
                    LearningPathEnrollment.employee_id == employee_id,
                )
            )
        ).scalar_one_or_none()
        if not enr:
            return {"enrolled": False}

        path = await db.get(LearningPath, enr.path_id)
        courses = sorted((path.required_courses_json or []) if path else [], key=lambda c: c.get("order", 0))
        completed = set(enr.completed_courses_json or [])
        next_course = self._find_next_available_course(courses, completed)
        return {
            "enrolled": True,
            "enrollment_id": str(enr.id),
            "path_id": str(enr.path_id),
            "status": enr.status,
            "progress_pct": enr.progress_pct,
            "completed_courses": list(completed),
            "current_course_id": enr.current_course_id,
            "next_course": next_course,
            "total_courses": len(courses),
        }

    @staticmethod
    def _find_next_available_course(
        courses: List[Dict[str, Any]], completed: set
    ) -> Optional[Dict[str, Any]]:
        """找到下一门可学（前置已满足且未完成）的课程"""
        for c in courses:
            cid = c.get("course_id")
            if cid in completed:
                continue
            prereqs = set(c.get("prerequisite_ids") or [])
            if prereqs.issubset(completed):
                return c
        return None

    async def complete_course(
        self,
        db: AsyncSession,
        *,
        enrollment_id: str,
        course_id: str,
        store_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """完成一课 — 校验前置 + 更新进度 + 自动发积分"""
        enr = await db.get(
            LearningPathEnrollment,
            uuid.UUID(enrollment_id) if isinstance(enrollment_id, str) else enrollment_id,
        )
        if not enr:
            raise ValueError(f"Enrollment {enrollment_id} not found")

        path = await db.get(LearningPath, enr.path_id)
        courses = sorted((path.required_courses_json or []) if path else [], key=lambda c: c.get("order", 0))

        # 校验该课程存在
        target = next((c for c in courses if c.get("course_id") == course_id), None)
        if not target:
            raise ValueError(f"Course {course_id} not in path")

        completed = set(enr.completed_courses_json or [])
        # 前置课程校验
        prereqs = set(target.get("prerequisite_ids") or [])
        if not prereqs.issubset(completed):
            raise ValueError(
                f"前置课程未完成：缺少 {prereqs - completed}"
            )

        completed.add(course_id)
        enr.completed_courses_json = list(completed)
        enr.progress_pct = int(round(len(completed) * 100 / max(1, len(courses))))
        # 下一门
        next_c = self._find_next_available_course(courses, completed)
        enr.current_course_id = next_c["course_id"] if next_c else None
        path_completed = len(completed) >= len(courses)
        if path_completed:
            enr.status = "completed"
            enr.completed_at = datetime.utcnow()
        else:
            enr.status = "in_progress"

        await db.flush()

        # 发积分 — 完成一课
        await learning_points_service.award(
            db,
            employee_id=enr.employee_id,
            event_type="course_complete",
            source_id=course_id,
            store_id=store_id,
        )
        # 路径全部完成再发一次
        if path_completed:
            await learning_points_service.award(
                db,
                employee_id=enr.employee_id,
                event_type="path_complete",
                source_id=str(enr.path_id),
                store_id=store_id,
            )
            await learning_points_service.check_badge_eligibility(
                db, employee_id=enr.employee_id
            )

        return {
            "enrollment_id": str(enr.id),
            "progress_pct": enr.progress_pct,
            "status": enr.status,
            "next_course": next_c,
            "path_completed": path_completed,
        }

    async def recommend_paths(
        self, db: AsyncSession, *, employee_id: str, position_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """推荐路径 — 基于岗位，排除已报名"""
        # 员工已报名的路径
        enrolled = {
            r.path_id
            for r in (
                await db.execute(
                    select(LearningPathEnrollment).where(
                        LearningPathEnrollment.employee_id == employee_id
                    )
                )
            ).scalars().all()
        }
        q = select(LearningPath).where(LearningPath.is_active.is_(True))
        if position_id:
            q = q.where(
                (LearningPath.target_position_id == position_id)
                | (LearningPath.target_position_id.is_(None))
            )
        rows = (await db.execute(q)).scalars().all()
        return [
            {
                "path_id": str(p.id),
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "estimated_hours": p.estimated_hours,
                "course_count": len(p.required_courses_json or []),
                "target_position_id": p.target_position_id,
            }
            for p in rows
            if p.id not in enrolled
        ][:10]


learning_path_service = LearningPathService()
