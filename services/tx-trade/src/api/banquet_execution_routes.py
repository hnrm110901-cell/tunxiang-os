"""宴会执行 API"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_execution_service import BanquetExecutionService


def _tid(r: Request) -> str:
    t = getattr(r.state, "tenant_id", None) or r.headers.get("X-Tenant-ID", "")
    if not t:
        raise HTTPException(400, "X-Tenant-ID required")
    return t


async def _db(r: Request) -> AsyncGenerator[AsyncSession, None]:
    async for s in get_db_with_tenant(_tid(r)):
        yield s


def _ok(d):
    return {"ok": True, "data": d, "error": None}


def _err(m, c=400):
    raise HTTPException(c, {"ok": False, "data": None, "error": {"message": m}})


router = APIRouter(prefix="/api/v1/banquet/execution", tags=["banquet-execution"])


class CreatePlanReq(BaseModel):
    banquet_id: str


class CompleteCheckpointReq(BaseModel):
    executor_id: Optional[str] = None
    executor_name: Optional[str] = None
    issue_note: Optional[str] = None


class EscalateReq(BaseModel):
    issue_note: str


@router.post("/plans")
async def create_plan(req: CreatePlanReq, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetExecutionService(db, _tid(r)).create_plan(req.banquet_id))
    except ValueError as e:
        _err(str(e))


@router.post("/plans/{plan_id}/start")
async def start(plan_id: str, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetExecutionService(db, _tid(r)).start_execution(plan_id))
    except ValueError as e:
        _err(str(e))


@router.get("/plans/{plan_id}/progress")
async def progress(plan_id: str, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetExecutionService(db, _tid(r)).get_progress(plan_id))
    except ValueError as e:
        _err(str(e), 404)


@router.post("/checkpoints/{log_id}/complete")
async def complete_cp(log_id: str, req: CompleteCheckpointReq, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(
            await BanquetExecutionService(db, _tid(r)).complete_checkpoint(
                log_id, req.executor_id, req.executor_name, req.issue_note
            )
        )
    except ValueError as e:
        _err(str(e))


@router.post("/checkpoints/{log_id}/escalate")
async def escalate_cp(log_id: str, req: EscalateReq, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetExecutionService(db, _tid(r)).escalate_checkpoint(log_id, req.issue_note))
    except ValueError as e:
        _err(str(e))
