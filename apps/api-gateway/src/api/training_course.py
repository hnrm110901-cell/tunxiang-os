"""
培训课程 API — D11 Must-Fix P0

端点：
  POST   /api/v1/hr/training/courses
  GET    /api/v1/hr/training/courses
  PUT    /api/v1/hr/training/courses/{course_id}
  DELETE /api/v1/hr/training/courses/{course_id}
  POST   /api/v1/hr/training/courses/{course_id}/materials
  GET    /api/v1/hr/training/courses/{course_id}/materials
  POST   /api/v1/hr/training/courses/{course_id}/enroll
  POST   /api/v1/hr/training/enrollments/{enrollment_id}/progress
  GET    /api/v1/hr/training/enrollments
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.training_course_service import TrainingCourseService

logger = structlog.get_logger()
router = APIRouter()


class CreateCourseRequest(BaseModel):
    brand_id: str
    store_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: str = "service"
    course_type: str = "online"
    applicable_positions: Optional[List[str]] = None
    duration_minutes: int = 60
    content_url: Optional[str] = None
    pass_score: int = 60
    credits: int = 1
    is_mandatory: bool = False
    sort_order: int = 0


class UpdateCourseRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    course_type: Optional[str] = None
    applicable_positions: Optional[List[str]] = None
    duration_minutes: Optional[int] = None
    content_url: Optional[str] = None
    pass_score: Optional[int] = None
    credits: Optional[int] = None
    is_mandatory: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    store_id: Optional[str] = None


class CreateMaterialRequest(BaseModel):
    title: str
    material_type: str = "video"  # video/pdf/ppt/image/text/link
    file_url: Optional[str] = None
    file_size_bytes: Optional[int] = None
    duration_seconds: Optional[int] = None
    text_content: Optional[str] = None
    sort_order: int = 0
    is_required: bool = True


class EnrollRequest(BaseModel):
    employee_id: str
    store_id: str


class ProgressRequest(BaseModel):
    progress_pct: int
    score: Optional[int] = None


@router.post("/hr/training/courses")
async def create_course(req: CreateCourseRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    result = await TrainingCourseService.create_course(db, req.dict())
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/hr/training/courses")
async def list_courses(
    brand_id: str = Query(..., description="品牌ID"),
    store_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = await TrainingCourseService.list_courses(
        db, brand_id=brand_id, store_id=store_id, category=category, is_active=is_active
    )
    return {"ok": True, "data": rows, "total": len(rows)}


@router.put("/hr/training/courses/{course_id}")
async def update_course(
    course_id: str, req: UpdateCourseRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    try:
        result = await TrainingCourseService.update_course(
            db, course_id, {k: v for k, v in req.dict().items() if v is not None}
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/hr/training/courses/{course_id}")
async def delete_course(course_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        result = await TrainingCourseService.delete_course(db, course_id)
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/hr/training/courses/{course_id}/materials")
async def add_material(
    course_id: str, req: CreateMaterialRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    result = await TrainingCourseService.add_material(db, course_id, req.dict())
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/hr/training/courses/{course_id}/materials")
async def list_materials(course_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    rows = await TrainingCourseService.list_materials(db, course_id)
    return {"ok": True, "data": rows, "total": len(rows)}


@router.post("/hr/training/courses/{course_id}/enroll")
async def enroll(course_id: str, req: EnrollRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    result = await TrainingCourseService.enroll(
        db, course_id=course_id, employee_id=req.employee_id, store_id=req.store_id
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/hr/training/enrollments/{enrollment_id}/progress")
async def update_progress(
    enrollment_id: str, req: ProgressRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    try:
        result = await TrainingCourseService.update_progress(
            db, enrollment_id, progress_pct=req.progress_pct, score=req.score
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/hr/training/enrollments")
async def list_enrollments(
    course_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = await TrainingCourseService.list_enrollments(db, course_id=course_id, employee_id=employee_id)
    return {"ok": True, "data": rows, "total": len(rows)}
