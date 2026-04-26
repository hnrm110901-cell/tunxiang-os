"""宴会产能 API"""

from datetime import date as date_cls
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_capacity_service import BanquetCapacityService


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


router = APIRouter(prefix="/api/v1/banquet/capacity", tags=["banquet-capacity"])


class ResolveConflictReq(BaseModel):
    resolution: str
    resolved_by: str


@router.get("/overview/{store_id}")
async def daily_overview(store_id: str, date: str = Query(...), request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetCapacityService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_daily_overview(store_id, date_cls.fromisoformat(date)))

@router.get("/check/{store_id}")
async def check_capacity(store_id: str, date: str = Query(...), time_slot: str = Query(...), required_dishes: int = Query(...), request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetCapacityService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.check_capacity(store_id, date_cls.fromisoformat(date), time_slot, required_dishes))

@router.get("/conflicts/{store_id}")
async def list_conflicts(store_id: str, date_from: str = Query(...), date_to: str = Query(...), status: Optional[str] = None, request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetCapacityService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.list_conflicts(store_id, date_cls.fromisoformat(date_from), date_cls.fromisoformat(date_to), status))

@router.patch("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, req: ResolveConflictReq, request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetCapacityService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.resolve_conflict(conflict_id, req.resolution, req.resolved_by))
    except ValueError as e:
        _err(str(e))

@router.get("/staff-suggestion/{store_id}")
async def staff_suggestion(store_id: str, date: str = Query(...), request: Request = None, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetCapacityService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.suggest_staff_requirement(store_id, date_cls.fromisoformat(date)))
