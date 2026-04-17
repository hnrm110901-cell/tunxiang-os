"""
培训课程服务 — D11 Must-Fix P0
提供课程/课件/报名的 CRUD + 进度管理。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class TrainingCourseService:
    """培训课程/课件/报名 CRUD 服务"""

    # ── Course ────────────────────────────────────────────────────────

    @staticmethod
    async def create_course(session: AsyncSession, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.models.training import TrainingCourse

        course = TrainingCourse(
            id=uuid.uuid4(),
            brand_id=data["brand_id"],
            store_id=data.get("store_id"),
            title=data["title"],
            description=data.get("description"),
            category=data.get("category", "service"),
            course_type=data.get("course_type", "online"),
            applicable_positions=data.get("applicable_positions"),
            duration_minutes=data.get("duration_minutes", 60),
            content_url=data.get("content_url"),
            pass_score=data.get("pass_score", 60),
            credits=data.get("credits", 1),
            is_mandatory=data.get("is_mandatory", False),
            sort_order=data.get("sort_order", 0),
            is_active=data.get("is_active", True),
        )
        session.add(course)
        await session.flush()
        logger.info("training_course.created", course_id=str(course.id), title=course.title)
        return {"id": str(course.id), "title": course.title}

    @staticmethod
    async def list_courses(
        session: AsyncSession,
        brand_id: str,
        store_id: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> List[Dict[str, Any]]:
        from src.models.training import TrainingCourse

        conds = [TrainingCourse.brand_id == brand_id]
        if store_id:
            # 品牌通用 OR 当前门店课程
            from sqlalchemy import or_
            conds.append(or_(TrainingCourse.store_id.is_(None), TrainingCourse.store_id == store_id))
        if category:
            conds.append(TrainingCourse.category == category)
        if is_active is not None:
            conds.append(TrainingCourse.is_active.is_(is_active))

        result = await session.execute(
            select(TrainingCourse).where(and_(*conds)).order_by(TrainingCourse.sort_order.asc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "title": r.title,
                "description": r.description,
                "category": r.category,
                "course_type": r.course_type,
                "duration_minutes": r.duration_minutes,
                "content_url": r.content_url,
                "credits": r.credits,
                "is_mandatory": r.is_mandatory,
                "is_active": r.is_active,
                "store_id": r.store_id,
            }
            for r in rows
        ]

    @staticmethod
    async def update_course(session: AsyncSession, course_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.models.training import TrainingCourse

        result = await session.execute(select(TrainingCourse).where(TrainingCourse.id == uuid.UUID(course_id)))
        course = result.scalar_one_or_none()
        if not course:
            raise ValueError("课程不存在")

        updatable = [
            "title", "description", "category", "course_type", "applicable_positions",
            "duration_minutes", "content_url", "pass_score", "credits",
            "is_mandatory", "sort_order", "is_active", "store_id",
        ]
        for f in updatable:
            if f in data:
                setattr(course, f, data[f])
        await session.flush()
        return {"id": str(course.id), "updated": True}

    @staticmethod
    async def delete_course(session: AsyncSession, course_id: str) -> Dict[str, Any]:
        """软删除（is_active=False）"""
        from src.models.training import TrainingCourse

        result = await session.execute(select(TrainingCourse).where(TrainingCourse.id == uuid.UUID(course_id)))
        course = result.scalar_one_or_none()
        if not course:
            raise ValueError("课程不存在")
        course.is_active = False
        await session.flush()
        return {"id": str(course.id), "deleted": True}

    # ── Material ──────────────────────────────────────────────────────

    @staticmethod
    async def add_material(session: AsyncSession, course_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.models.training import TrainingMaterial

        mat = TrainingMaterial(
            id=uuid.uuid4(),
            course_id=uuid.UUID(course_id),
            title=data["title"],
            material_type=data.get("material_type", "video"),
            file_url=data.get("file_url"),
            file_size_bytes=data.get("file_size_bytes"),
            duration_seconds=data.get("duration_seconds"),
            text_content=data.get("text_content"),
            sort_order=data.get("sort_order", 0),
            is_required=data.get("is_required", True),
            is_active=data.get("is_active", True),
        )
        session.add(mat)
        await session.flush()
        return {"id": str(mat.id), "title": mat.title}

    @staticmethod
    async def list_materials(session: AsyncSession, course_id: str) -> List[Dict[str, Any]]:
        from src.models.training import TrainingMaterial

        result = await session.execute(
            select(TrainingMaterial)
            .where(and_(TrainingMaterial.course_id == uuid.UUID(course_id), TrainingMaterial.is_active.is_(True)))
            .order_by(TrainingMaterial.sort_order.asc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "title": r.title,
                "material_type": r.material_type,
                "file_url": r.file_url,
                "duration_seconds": r.duration_seconds,
                "text_content": r.text_content,
                "is_required": r.is_required,
                "sort_order": r.sort_order,
            }
            for r in rows
        ]

    # ── Enrollment ────────────────────────────────────────────────────

    @staticmethod
    async def enroll(
        session: AsyncSession, course_id: str, employee_id: str, store_id: str
    ) -> Dict[str, Any]:
        from src.models.training import TrainingEnrollment

        # 幂等：若已报名直接返回
        existing = await session.execute(
            select(TrainingEnrollment).where(
                and_(
                    TrainingEnrollment.course_id == uuid.UUID(course_id),
                    TrainingEnrollment.employee_id == employee_id,
                )
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            return {"id": str(row.id), "status": row.status, "idempotent": True}

        enr = TrainingEnrollment(
            id=uuid.uuid4(),
            store_id=store_id,
            employee_id=employee_id,
            course_id=uuid.UUID(course_id),
            status="enrolled",
            enrolled_at=datetime.utcnow(),
            progress_pct=0,
        )
        session.add(enr)
        await session.flush()
        return {"id": str(enr.id), "status": enr.status}

    @staticmethod
    async def update_progress(
        session: AsyncSession, enrollment_id: str, progress_pct: int, score: Optional[int] = None
    ) -> Dict[str, Any]:
        from src.models.training import TrainingEnrollment

        result = await session.execute(
            select(TrainingEnrollment).where(TrainingEnrollment.id == uuid.UUID(enrollment_id))
        )
        enr = result.scalar_one_or_none()
        if not enr:
            raise ValueError("报名记录不存在")

        progress_pct = max(0, min(100, int(progress_pct)))
        enr.progress_pct = progress_pct
        if enr.started_at is None and progress_pct > 0:
            enr.started_at = datetime.utcnow()
            enr.status = "in_progress"
        if score is not None:
            enr.score = int(score)
        if progress_pct >= 100:
            enr.status = "completed"
            enr.completed_at = datetime.utcnow()
        await session.flush()
        return {"id": str(enr.id), "status": enr.status, "progress_pct": enr.progress_pct}

    @staticmethod
    async def list_enrollments(
        session: AsyncSession, course_id: Optional[str] = None, employee_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from src.models.training import TrainingEnrollment

        conds = []
        if course_id:
            conds.append(TrainingEnrollment.course_id == uuid.UUID(course_id))
        if employee_id:
            conds.append(TrainingEnrollment.employee_id == employee_id)

        q = select(TrainingEnrollment)
        if conds:
            q = q.where(and_(*conds))
        q = q.order_by(TrainingEnrollment.enrolled_at.desc())

        result = await session.execute(q)
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "employee_id": r.employee_id,
                "course_id": str(r.course_id),
                "status": r.status,
                "progress_pct": r.progress_pct,
                "score": r.score,
                "enrolled_at": r.enrolled_at.isoformat() if r.enrolled_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
