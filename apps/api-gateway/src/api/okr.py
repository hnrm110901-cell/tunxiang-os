"""
OKR API — 目标管理 / KR 打卡 / 团队树 / 对齐 / AI 推荐
前缀: /api/v1/hr/okr
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.services.okr_ai_service import okr_ai_service
from src.services.okr_service import okr_service

router = APIRouter(prefix="/api/v1/hr/okr", tags=["hr-okr"])


class ObjectiveIn(BaseModel):
    owner_id: str
    title: str
    period: str
    owner_type: str = "personal"
    description: Optional[str] = None
    parent_objective_id: Optional[str] = None
    target_value: Optional[float] = None
    weight: int = 100
    store_id: Optional[str] = None


class KRIn(BaseModel):
    objective_id: str
    title: str
    metric_type: str = "numeric"
    start_value: float = 0.0
    target_value: float = 0.0
    unit: Optional[str] = None
    weight: int = 100
    owner_id: Optional[str] = None


class UpdateIn(BaseModel):
    value: float
    comment: Optional[str] = None
    evidence_url: Optional[str] = None
    updated_by: str


class AlignIn(BaseModel):
    parent_obj_id: str
    child_obj_id: str
    alignment_type: str = "contribute_to"
    notes: Optional[str] = None


class SuggestKRIn(BaseModel):
    objective_title: str
    context: str = ""


@router.post("/objectives")
async def create_objective(payload: ObjectiveIn, db: AsyncSession = Depends(get_db)):
    oid = await okr_service.create_objective(db, **payload.model_dump())
    await db.commit()
    return {"objective_id": oid}


@router.post("/key-results")
async def create_kr(payload: KRIn, db: AsyncSession = Depends(get_db)):
    kid = await okr_service.add_key_result(db, **payload.model_dump())
    await db.commit()
    return {"kr_id": kid}


@router.post("/key-results/{kr_id}/update")
async def update_kr_progress(
    kr_id: str,
    payload: UpdateIn,
    db: AsyncSession = Depends(get_db),
):
    result = await okr_service.update_progress(
        db,
        kr_id=kr_id,
        value=payload.value,
        comment=payload.comment,
        evidence_url=payload.evidence_url,
        updated_by=payload.updated_by,
    )
    await db.commit()
    return result


@router.get("/my")
async def my_okr(
    owner_id: str = Query(...),
    period: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    return await okr_service.get_my_okr(db, owner_id=owner_id, period=period)


@router.get("/team-tree/{manager_id}")
async def team_okr_tree(
    manager_id: str,
    period: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await okr_service.get_team_okr_tree(db, manager_id=manager_id, period=period)


@router.post("/alignments")
async def create_alignment(payload: AlignIn, db: AsyncSession = Depends(get_db)):
    aid = await okr_service.align(
        db,
        parent_obj_id=payload.parent_obj_id,
        child_obj_id=payload.child_obj_id,
        alignment_type=payload.alignment_type,
        notes=payload.notes,
    )
    await db.commit()
    return {"alignment_id": aid}


@router.post("/ai/suggest-krs")
async def ai_suggest_krs(payload: SuggestKRIn):
    """LLM 推荐 SMART KR；失败返回空数组"""
    items = await okr_ai_service.suggest_key_results(
        objective_title=payload.objective_title, context=payload.context
    )
    return {"items": items}
