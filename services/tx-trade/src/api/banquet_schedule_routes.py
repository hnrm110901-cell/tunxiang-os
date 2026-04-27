"""宴会日调度 API"""

from datetime import date as date_cls
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_scheduler_service import BanquetSchedulerService


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_with_tenant(_get_tenant_id(request)):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


router = APIRouter(prefix="/api/v1/banquet/schedule", tags=["banquet-schedule"])


class GenerateScheduleReq(BaseModel):
    store_id: str
    date: str


class ConfirmReq(BaseModel):
    confirmed_by: str


class StaffAllocReq(BaseModel):
    assignments: list[dict]


@router.post("/generate")
async def generate_schedule(req: GenerateScheduleReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.generate_daily_schedule(req.store_id, date_cls.fromisoformat(req.date)))


@router.get("/timeline/{store_id}/{date}")
async def get_timeline(store_id: str, date: str, request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_timeline(store_id, date_cls.fromisoformat(date)))


@router.get("/resources/{store_id}/{date}")
async def get_resources(store_id: str, date: str, request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_resource_summary(store_id, date_cls.fromisoformat(date)))


@router.get("/list/{store_id}")
async def list_schedules(
    store_id: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(_get_db_session),
):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.list_schedules(store_id, date_cls.fromisoformat(date_from), date_cls.fromisoformat(date_to)))


@router.get("/{store_id}/{date}")
async def get_schedule(store_id: str, date: str, request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_schedule(store_id, date_cls.fromisoformat(date)))


@router.post("/{schedule_id}/confirm")
async def confirm_schedule(
    schedule_id: str, req: ConfirmReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.confirm_schedule(schedule_id, req.confirmed_by))
    except ValueError as e:
        _err(str(e))


@router.post("/{schedule_id}/staff")
async def allocate_staff(
    schedule_id: str, req: StaffAllocReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    svc = BanquetSchedulerService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.allocate_staff(schedule_id, req.assignments))
