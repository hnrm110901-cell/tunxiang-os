"""
脉搏调研 API — 模板 / 下发 / 作答 / 汇总 / 趋势
前缀: /api/v1/hr/pulse
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.services.pulse_survey_service import pulse_survey_service

router = APIRouter(prefix="/api/v1/hr/pulse", tags=["hr-pulse-survey"])


class TemplateIn(BaseModel):
    code: str
    name: str
    questions: List[Dict[str, Any]]
    frequency: str = "monthly"
    target_scope: str = "all"
    allow_anonymous: bool = True
    created_by: Optional[str] = None


class SendIn(BaseModel):
    template_id: str
    store_id: Optional[str] = None
    target_employee_ids: List[str] = []
    scheduled_date: Optional[date] = None
    response_days: int = 7


class ResponseIn(BaseModel):
    instance_id: str
    employee_id: str
    responses: List[Dict[str, Any]]
    is_anonymous: bool = False


@router.post("/templates")
async def create_template(payload: TemplateIn, db: AsyncSession = Depends(get_db)):
    tid = await pulse_survey_service.create_template(db, **payload.model_dump())
    await db.commit()
    return {"template_id": tid}


@router.post("/surveys/send")
async def send_survey(payload: SendIn, db: AsyncSession = Depends(get_db)):
    iid = await pulse_survey_service.send_survey(db, **payload.model_dump())
    await db.commit()
    return {"instance_id": iid}


@router.post("/responses")
async def submit_response(payload: ResponseIn, db: AsyncSession = Depends(get_db)):
    rid = await pulse_survey_service.submit_response(db, **payload.model_dump())
    await db.commit()
    return {"response_id": rid}


@router.get("/instances/{instance_id}/results")
async def instance_results(
    instance_id: str,
    with_sentiment: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    summary = await pulse_survey_service.aggregate_results(db, instance_id=instance_id)
    if with_sentiment:
        summary["sentiment"] = await pulse_survey_service.sentiment_analysis(
            db, instance_id=instance_id
        )
    await db.commit()
    return summary


@router.get("/trends/{template_id}")
async def trends(
    template_id: str,
    last_n_periods: int = Query(6),
    db: AsyncSession = Depends(get_db),
):
    return {
        "template_id": template_id,
        "periods": await pulse_survey_service.trend_analysis(
            db, template_id=template_id, last_n_periods=last_n_periods
        ),
    }
