"""宴会排产 API"""

from typing import AsyncGenerator, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db_with_tenant
from ..services.banquet_production_service import BanquetProductionService


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid

async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}

def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


router = APIRouter(prefix="/api/v1/banquet/production", tags=["banquet-production"])


class GeneratePlanReq(BaseModel):
    banquet_id: str

class ConfirmPlanReq(BaseModel):
    confirmed_by: str

class AssignTasksReq(BaseModel):
    plan_id: str
    assignments: list[dict]

class UpdateTaskStatusReq(BaseModel):
    status: str


@router.post("/plans")
async def generate_plan(req: GeneratePlanReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.generate_plan(req.banquet_id))
    except ValueError as e:
        _err(str(e))

@router.get("/plans/by-banquet/{banquet_id}")
async def get_plan_by_banquet(banquet_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_plan_by_banquet(banquet_id))

@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.get_plan(plan_id))
    except ValueError as e:
        _err(str(e), 404)

@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(plan_id: str, req: ConfirmPlanReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.confirm_plan(plan_id, req.confirmed_by))
    except ValueError as e:
        _err(str(e))

@router.post("/plans/{plan_id}/start")
async def start_execution(plan_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.start_execution(plan_id))
    except ValueError as e:
        _err(str(e))

@router.post("/plans/{plan_id}/complete")
async def complete_plan(plan_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.complete_plan(plan_id))
    except ValueError as e:
        _err(str(e))

@router.post("/tasks/assign")
async def assign_tasks(req: AssignTasksReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.assign_tasks(req.plan_id, req.assignments))

@router.patch("/tasks/{task_id}/status")
async def update_task_status(task_id: str, req: UpdateTaskStatusReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.update_task_status(task_id, req.status))
    except ValueError as e:
        _err(str(e))

@router.get("/plans/{plan_id}/progress")
async def get_course_progress(plan_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_course_progress(plan_id))

@router.get("/plans/{plan_id}/timeline")
async def get_kitchen_timeline(plan_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetProductionService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_kitchen_timeline(plan_id))
