"""
E-learning 学习地图 + 积分 + 徽章 API
前缀: /api/v1/hr/learning
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.models.learning_path import LearningAchievement
from sqlalchemy import select

from src.services.learning_path_service import learning_path_service
from src.services.learning_points_service import learning_points_service

router = APIRouter(prefix="/api/v1/hr/learning", tags=["hr-learning"])


class PathIn(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    target_position: Optional[str] = None
    courses: List[Dict[str, Any]] = []
    estimated_hours: int = 0
    created_by: Optional[str] = None


class EnrollIn(BaseModel):
    employee_id: str


class CompleteIn(BaseModel):
    enrollment_id: str
    course_id: str
    store_id: Optional[str] = None


@router.post("/paths")
async def create_path(payload: PathIn, db: AsyncSession = Depends(get_db)):
    pid = await learning_path_service.create_path(db, **payload.model_dump())
    await db.commit()
    return {"path_id": pid}


@router.post("/paths/{path_id}/enroll")
async def enroll_path(path_id: str, payload: EnrollIn, db: AsyncSession = Depends(get_db)):
    eid = await learning_path_service.enroll(
        db, path_id=path_id, employee_id=payload.employee_id
    )
    await db.commit()
    return {"enrollment_id": eid}


@router.get("/my-paths")
async def my_paths(
    employee_id: str = Query(...),
    path_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """单一路径进度（传 path_id）或推荐路径列表（不传）"""
    if path_id:
        return await learning_path_service.get_progress(
            db, employee_id=employee_id, path_id=path_id
        )
    return await learning_path_service.recommend_paths(db, employee_id=employee_id)


@router.post("/complete")
async def complete_course(payload: CompleteIn, db: AsyncSession = Depends(get_db)):
    result = await learning_path_service.complete_course(
        db,
        enrollment_id=payload.enrollment_id,
        course_id=payload.course_id,
        store_id=payload.store_id,
    )
    await db.commit()
    return result


@router.get("/leaderboard/{store_id}")
async def leaderboard(
    store_id: str,
    period: str = Query("month"),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    return {
        "store_id": store_id,
        "period": period,
        "items": await learning_points_service.get_leaderboard(
            db, store_id=store_id, period=period, limit=limit
        ),
    }


@router.get("/points/my")
async def my_points(
    employee_id: str = Query(...),
    recent: int = Query(10),
    db: AsyncSession = Depends(get_db),
):
    return await learning_points_service.get_my_points(
        db, employee_id=employee_id, recent=recent
    )


@router.get("/achievements/my")
async def my_achievements(
    employee_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(LearningAchievement).where(
                LearningAchievement.employee_id == employee_id
            )
        )
    ).scalars().all()
    return {
        "employee_id": employee_id,
        "items": [
            {
                "badge_code": r.badge_code,
                "badge_name": r.badge_name,
                "earned_at": r.earned_at.isoformat() if r.earned_at else None,
                "source_path_id": str(r.source_path_id) if r.source_path_id else None,
            }
            for r in rows
        ],
    }
