"""宴会厅管理 API — 场地CRUD / 可用性查询 / 预留 / 确认 / 日历 / 利用率"""

from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_crm_service import BanquetCRMService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquet/venues", tags=["banquet-venue"])


# ─── 依赖注入 ───


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
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── Request Models ───


class CreateVenueReq(BaseModel):
    store_id: str
    name: str = Field(min_length=1)
    venue_type: str  # banquet_hall / vip_room / outdoor / multi_purpose
    floor: Optional[str] = None
    max_tables: int = Field(ge=1)
    min_tables: int = Field(1, ge=1)
    max_guests: int = Field(ge=1)
    area_sqm: Optional[float] = Field(None, gt=0)
    amenities: list[str] = Field(default_factory=list)
    hourly_rate_fen: int = Field(0, ge=0)
    notes: Optional[str] = None


class UpdateVenueReq(BaseModel):
    name: Optional[str] = None
    venue_type: Optional[str] = None
    floor: Optional[str] = None
    max_tables: Optional[int] = Field(None, ge=1)
    min_tables: Optional[int] = Field(None, ge=1)
    max_guests: Optional[int] = Field(None, ge=1)
    area_sqm: Optional[float] = Field(None, gt=0)
    amenities: Optional[list[str]] = None
    hourly_rate_fen: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class HoldVenueReq(BaseModel):
    lead_id: str
    event_date: str  # YYYY-MM-DD
    time_slot: str  # lunch / dinner / full_day / custom
    start_time: Optional[str] = None  # HH:MM (for custom)
    end_time: Optional[str] = None  # HH:MM (for custom)
    hold_until: Optional[str] = None  # ISO datetime, auto-release after
    notes: Optional[str] = None


class ConfirmBookingReq(BaseModel):
    confirmed_by: Optional[str] = None
    notes: Optional[str] = None


# ─── Endpoints: Venues ───


@router.post("/")
async def create_venue(
    body: CreateVenueReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建宴会厅"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.create_venue(body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/")
async def list_venues(
    request: Request,
    store_id: Optional[str] = Query(None),
    venue_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(_get_db_session),
):
    """列表查询宴会厅"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_venues(store_id=store_id, venue_type=venue_type, is_active=is_active)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/calendar/{store_id}")
async def get_venue_calendar(
    store_id: str,
    request: Request,
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(_get_db_session),
):
    """获取场地日历视图"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_venue_calendar(store_id=store_id, date_from=date_from, date_to=date_to)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/utilization/{store_id}")
async def get_venue_utilization(
    store_id: str,
    request: Request,
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
    db: AsyncSession = Depends(_get_db_session),
):
    """获取场地利用率统计"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_venue_utilization(store_id=store_id, date_from=date_from, date_to=date_to)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{venue_id}")
async def get_venue(
    venue_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取宴会厅详情"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_venue(venue_id=venue_id)
        if not result:
            _err("Venue not found", code=404)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/{venue_id}")
async def update_venue(
    venue_id: str,
    body: UpdateVenueReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新宴会厅信息"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        updates = body.model_dump(exclude_unset=True)
        result = await svc.update_venue(venue_id=venue_id, updates=updates)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{venue_id}/availability")
async def check_availability(
    venue_id: str,
    request: Request,
    date: str = Query(..., description="Date YYYY-MM-DD"),
    time_slot: Optional[str] = Query(None, description="lunch / dinner / full_day"),
    db: AsyncSession = Depends(_get_db_session),
):
    """查询场地可用性"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.check_venue_availability(venue_id=venue_id, date=date, time_slot=time_slot)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{venue_id}/hold")
async def hold_venue(
    venue_id: str,
    body: HoldVenueReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """预留场地"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.hold_venue(venue_id=venue_id, data=body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Endpoints: Bookings ───


@router.patch("/bookings/{booking_id}/confirm")
async def confirm_booking(
    booking_id: str,
    body: ConfirmBookingReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """确认场地预订"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.confirm_venue_booking(
            booking_id=booking_id,
            confirmed_by=body.confirmed_by,
            notes=body.notes,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.patch("/bookings/{booking_id}/release")
async def release_booking(
    booking_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """释放场地预订"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.release_venue_booking(booking_id=booking_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))
