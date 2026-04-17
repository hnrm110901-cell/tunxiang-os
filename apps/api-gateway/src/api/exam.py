"""
考试 API — D11 Should-Fix P1

端点：
  POST  /api/v1/hr/training/exam/questions
  PUT   /api/v1/hr/training/exam/questions/{id}
  GET   /api/v1/hr/training/exam/questions?course_id=...
  POST  /api/v1/hr/training/exam/papers
  POST  /api/v1/hr/training/exam/papers/auto
  GET   /api/v1/hr/training/exam/papers/{id}       # 答题视图，不含正确答案
  POST  /api/v1/hr/training/exam/attempts          # 开始考试
  POST  /api/v1/hr/training/exam/attempts/{id}/submit
  POST  /api/v1/hr/training/exam/attempts/{id}/grade-essay
  GET   /api/v1/hr/training/exam/attempts/{id}/result
  GET   /api/v1/hr/training/exam/certificates/my?employee_id=...
  GET   /api/v1/hr/training/exam/certificates/expiring?days_ahead=30
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.exam_service import ExamService

logger = structlog.get_logger()
router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────


class CreateQuestionRequest(BaseModel):
    course_id: str
    type: str = Field("single", description="single/multi/judge/fill/essay")
    stem: str
    options_json: Optional[List[Dict[str, Any]]] = None
    correct_answer_json: Optional[Any] = None
    score: int = 5
    difficulty: int = 3
    explanation: Optional[str] = None


class UpdateQuestionRequest(BaseModel):
    type: Optional[str] = None
    stem: Optional[str] = None
    options_json: Optional[List[Dict[str, Any]]] = None
    correct_answer_json: Optional[Any] = None
    score: Optional[int] = None
    difficulty: Optional[int] = None
    explanation: Optional[str] = None
    is_active: Optional[bool] = None


class CreatePaperRequest(BaseModel):
    course_id: str
    title: str
    question_ids: List[str]
    pass_score: int = 60
    duration_min: int = 30
    is_random: bool = False
    created_by: Optional[str] = None


class AutoPaperRequest(BaseModel):
    course_id: str
    title: str = "自动组卷"
    rules: Dict[str, Any]  # {"difficulty": {"1": 3, "2": 5}}
    pass_score: int = 60
    duration_min: int = 30
    created_by: Optional[str] = None


class StartAttemptRequest(BaseModel):
    paper_id: str
    employee_id: str
    store_id: str


class SubmitAttemptRequest(BaseModel):
    answers: Dict[str, Any]


class GradeEssayRequest(BaseModel):
    item_scores: Dict[str, int]
    reviewer: str


# ── 题库 ──────────────────────────────────────────────────────────


@router.post("/hr/training/exam/questions")
async def create_question(body: CreateQuestionRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.create_question(db, body.course_id, **body.model_dump(exclude={"course_id"}))
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        logger.error("exam.question.create_failed", error=str(e))
        raise HTTPException(400, str(e))


@router.put("/hr/training/exam/questions/{question_id}")
async def update_question(question_id: str, body: UpdateQuestionRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        out = await ExamService.update_question(db, question_id, data)
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.get("/hr/training/exam/questions")
async def list_questions(course_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    try:
        data = await ExamService.list_by_course(db, course_id)
        return {"success": True, "data": data, "total": len(data)}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── 试卷 ──────────────────────────────────────────────────────────


@router.post("/hr/training/exam/papers")
async def create_paper(body: CreatePaperRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.create_paper(
            db,
            course_id=body.course_id,
            question_ids=body.question_ids,
            title=body.title,
            pass_score=body.pass_score,
            duration_min=body.duration_min,
            is_random=body.is_random,
            created_by=body.created_by,
        )
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.post("/hr/training/exam/papers/auto")
async def auto_generate_paper(body: AutoPaperRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.auto_generate_paper(
            db,
            course_id=body.course_id,
            rules=body.rules,
            title=body.title,
            pass_score=body.pass_score,
            duration_min=body.duration_min,
            created_by=body.created_by,
        )
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.get("/hr/training/exam/papers/{paper_id}")
async def get_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    """答题视图：不返回正确答案"""
    try:
        data = await ExamService.get_paper(db, paper_id, include_answers=False)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(404, str(e))


# ── 考试流程 ──────────────────────────────────────────────────────


@router.post("/hr/training/exam/attempts")
async def start_attempt(body: StartAttemptRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.start_attempt(db, body.paper_id, body.employee_id, body.store_id)
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.post("/hr/training/exam/attempts/{attempt_id}/submit")
async def submit_attempt(attempt_id: str, body: SubmitAttemptRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.submit_attempt(db, attempt_id, body.answers)
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.post("/hr/training/exam/attempts/{attempt_id}/grade-essay")
async def grade_essay(attempt_id: str, body: GradeEssayRequest, db: AsyncSession = Depends(get_db)):
    try:
        out = await ExamService.grade_essay(db, attempt_id, body.item_scores, body.reviewer)
        await db.commit()
        return {"success": True, "data": out}
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.get("/hr/training/exam/attempts/{attempt_id}/result")
async def get_attempt_result(attempt_id: str, db: AsyncSession = Depends(get_db)):
    try:
        data = await ExamService.get_attempt_result(db, attempt_id)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(404, str(e))


# ── 证书 ──────────────────────────────────────────────────────────


@router.get("/hr/training/exam/certificates/my")
async def my_certificates(employee_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    try:
        data = await ExamService.list_my_certificates(db, employee_id)
        return {"success": True, "data": data, "total": len(data)}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/hr/training/exam/certificates/expiring")
async def expiring_certs(days_ahead: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)):
    try:
        data = await ExamService.list_expiring_certs(db, days_ahead)
        return {"success": True, "data": data, "total": len(data)}
    except Exception as e:
        raise HTTPException(400, str(e))
