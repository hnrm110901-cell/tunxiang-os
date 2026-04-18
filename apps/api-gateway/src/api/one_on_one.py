"""
1-on-1 面谈 API
POST /api/v1/hr/1on1/templates               模板管理
POST /api/v1/hr/1on1/meetings                预约
POST /api/v1/hr/1on1/meetings/{id}/start     开始
POST /api/v1/hr/1on1/meetings/{id}/complete  结束+AI总结
GET  /api/v1/hr/1on1/my?role=initiator|participant
GET  /api/v1/hr/1on1/team-stats/{manager_id}?days=30
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.one_on_one_ai_service import OneOnOneAIService
from ..services.one_on_one_service import OneOnOneService

logger = structlog.get_logger()
router = APIRouter()


class CreateTemplateReq(BaseModel):
    name: str
    topic_category: str
    questions: List[dict]
    is_default: bool = False
    created_by: Optional[str] = None


class ScheduleMeetingReq(BaseModel):
    initiator_id: str
    participant_id: str
    scheduled_at: datetime
    template_id: Optional[uuid.UUID] = None
    duration_min: int = 30
    location: Optional[str] = None


class CompleteMeetingReq(BaseModel):
    notes: str
    action_items: Optional[List[dict]] = None
    auto_ai_summary: bool = True


@router.post("/hr/1on1/templates")
async def create_template(req: CreateTemplateReq, db: AsyncSession = Depends(get_db)):
    svc = OneOnOneService(db)
    try:
        tpl = await svc.create_template(
            name=req.name,
            topic_category=req.topic_category,
            questions=req.questions,
            is_default=req.is_default,
            created_by=req.created_by,
        )
        await db.commit()
        return {"id": str(tpl.id), "name": tpl.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hr/1on1/meetings")
async def schedule_meeting(req: ScheduleMeetingReq, db: AsyncSession = Depends(get_db)):
    svc = OneOnOneService(db)
    try:
        m = await svc.schedule_meeting(
            initiator_id=req.initiator_id,
            participant_id=req.participant_id,
            scheduled_at=req.scheduled_at,
            template_id=req.template_id,
            duration_min=req.duration_min,
            location=req.location,
        )
        await db.commit()
        return {"id": str(m.id), "status": m.status, "scheduled_at": m.scheduled_at.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/hr/1on1/meetings/{meeting_id}/start")
async def start_meeting(meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = OneOnOneService(db)
    try:
        m = await svc.start_meeting(meeting_id)
        await db.commit()
        return {"id": str(m.id), "status": m.status, "started_at": m.started_at.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hr/1on1/meetings/{meeting_id}/complete")
async def complete_meeting(meeting_id: uuid.UUID, req: CompleteMeetingReq, db: AsyncSession = Depends(get_db)):
    svc = OneOnOneService(db)
    try:
        m = await svc.complete_meeting(
            meeting_id=meeting_id,
            notes=req.notes,
            action_items=req.action_items,
            auto_ai_summary=req.auto_ai_summary,
        )
        await db.commit()
        return {
            "id": str(m.id),
            "status": m.status,
            "ai_summary": m.ai_summary or "",
            "action_items": m.action_items_json or [],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hr/1on1/my")
async def list_my_meetings(
    user_id: str = Query(...),
    role: str = Query("participant"),
    db: AsyncSession = Depends(get_db),
):
    svc = OneOnOneService(db)
    try:
        rows = await svc.list_my_meetings(user_id=user_id, role=role)
        return [
            {
                "id": str(m.id),
                "initiator_id": m.initiator_id,
                "participant_id": m.participant_id,
                "scheduled_at": m.scheduled_at.isoformat(),
                "status": m.status,
            }
            for m in rows
        ]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hr/1on1/team-stats/{manager_id}")
async def team_stats(manager_id: str, days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)):
    svc = OneOnOneService(db)
    return await svc.get_team_1on1_stats(manager_id=manager_id, period_days=days)


@router.post("/hr/1on1/ai/suggest-topics")
async def suggest_topics(manager_id: str, participant_id: str, db: AsyncSession = Depends(get_db)):
    svc = OneOnOneAIService(db)
    topics = await svc.suggest_topics(manager_id=manager_id, participant_id=participant_id)
    return {"topics": topics}
