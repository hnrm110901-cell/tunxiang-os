"""
人才盘点 API
POST /api/v1/hr/talent/assessments          新建盘点
GET  /api/v1/hr/talent/nine-box/{store_id}  九宫格矩阵
POST /api/v1/hr/talent/pool                 入池
GET  /api/v1/hr/talent/succession/{pos_id}  继任方案
POST /api/v1/hr/talent/ai/development-plan  LLM 发展建议
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.nine_box_ai_service import NineBoxAIService
from ..services.talent_assessment_service import TalentAssessmentService

logger = structlog.get_logger()
router = APIRouter()


class CreateAssessmentReq(BaseModel):
    employee_id: str
    assessor_id: str
    performance_score: int
    potential_score: int
    strengths: Optional[str] = None
    development_areas: Optional[str] = None
    career_path: Optional[str] = None
    assessment_date: Optional[date] = None


class AddToPoolReq(BaseModel):
    employee_id: str
    pool_type: str  # high_potential|successor|key_position|watch_list
    target_position: Optional[str] = None
    readiness: Optional[str] = None
    notes: Optional[str] = None


class DevPlanReq(BaseModel):
    assessment_id: uuid.UUID


@router.post("/hr/talent/assessments")
async def create_assessment(req: CreateAssessmentReq, db: AsyncSession = Depends(get_db)):
    svc = TalentAssessmentService(db)
    try:
        ta = await svc.create_assessment(
            employee_id=req.employee_id,
            assessor_id=req.assessor_id,
            performance_score=req.performance_score,
            potential_score=req.potential_score,
            strengths=req.strengths,
            development_areas=req.development_areas,
            career_path=req.career_path,
            assessment_date=req.assessment_date,
        )
        await db.commit()
        return {"id": str(ta.id), "nine_box_cell": ta.nine_box_cell}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hr/talent/nine-box/{store_id}")
async def nine_box_matrix(
    store_id: str,
    as_of: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    svc = TalentAssessmentService(db)
    matrix = await svc.compute_nine_box_matrix(store_id=store_id, as_of_date=as_of)
    return {"store_id": store_id, "matrix": matrix}


@router.post("/hr/talent/pool")
async def add_to_pool(req: AddToPoolReq, db: AsyncSession = Depends(get_db)):
    svc = TalentAssessmentService(db)
    try:
        row = await svc.add_to_talent_pool(
            employee_id=req.employee_id,
            pool_type=req.pool_type,
            target_position=req.target_position,
            readiness=req.readiness,
            notes=req.notes,
        )
        await db.commit()
        return {"id": str(row.id), "pool_type": row.pool_type}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hr/talent/succession/{position_id}")
async def get_succession(position_id: str, db: AsyncSession = Depends(get_db)):
    svc = TalentAssessmentService(db)
    plan = await svc.generate_successor_plan(key_position_id=position_id)
    await db.commit()
    return {
        "id": str(plan.id),
        "key_position_id": plan.key_position_id,
        "successor_id": plan.successor_id,
        "readiness": plan.readiness,
        "candidates": plan.candidates_json or [],
    }


@router.post("/hr/talent/ai/development-plan")
async def ai_development_plan(req: DevPlanReq, db: AsyncSession = Depends(get_db)):
    svc = NineBoxAIService(db)
    plan = await svc.generate_development_plan(req.assessment_id)
    await db.commit()
    return {"assessment_id": str(req.assessment_id), "development_plan": plan}
