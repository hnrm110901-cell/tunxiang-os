"""大厨到家 API — 10个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.chef_at_home import (
    calculate_price,
    complete_service,
    confirm_booking,
    create_booking,
    get_booking_history,
    get_chef_profile,
    get_chef_schedule,
    list_available_chefs,
    rate_service,
    start_service,
)

router = APIRouter(prefix="/api/v1/chef-at-home", tags=["chef-at-home"])


# ─── 通用辅助 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """获取带租户隔离的DB session"""
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    """抛出 HTTPException"""
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求模型 ───


class DishItem(BaseModel):
    dish_id: str
    name: str
    quantity: int = Field(ge=1, default=1)
    price_fen: int = Field(ge=0)


class CreateBookingReq(BaseModel):
    customer_id: str = Field(min_length=1)
    dishes: list[DishItem] = Field(min_length=1)
    chef_id: str = Field(min_length=1)
    service_datetime: str = Field(description="ISO格式服务时间")
    address: str = Field(min_length=1)
    guest_count: int = Field(ge=1)


class ConfirmBookingReq(BaseModel):
    payment_id: str = Field(min_length=1)


class StartServiceReq(BaseModel):
    chef_id: str = Field(min_length=1)


class CompleteServiceReq(BaseModel):
    photos: list[str] = Field(default_factory=list)


class RateServiceReq(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="")


class CalculatePriceReq(BaseModel):
    dishes: list[DishItem] = Field(min_length=1)
    guest_count: int = Field(ge=1)
    distance_km: float = Field(ge=0, default=10.0)


# ═══════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════


@router.post("/bookings")
async def api_create_booking(
    req: CreateBookingReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建大厨到家预约"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await create_booking(
            customer_id=req.customer_id,
            dishes=[d.model_dump() for d in req.dishes],
            chef_id=req.chef_id,
            service_datetime=req.service_datetime,
            address=req.address,
            guest_count=req.guest_count,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/chefs")
async def api_list_chefs(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    area: str = Query("", description="区域"),
    cuisine_type: Optional[str] = Query(None, description="菜系"),
):
    """查询可用厨师列表"""
    tenant_id = _get_tenant_id(request)
    result = await list_available_chefs(
        date=date,
        area=area,
        cuisine_type=cuisine_type,
        tenant_id=tenant_id,
        db=db,
    )
    return _ok(result)


@router.get("/chefs/{chef_id}")
async def api_get_chef_profile(
    chef_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取厨师详细档案"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await get_chef_profile(chef_id=chef_id, tenant_id=tenant_id, db=db)
        return _ok(result)
    except ValueError as e:
        _err(str(e), code=404)


@router.get("/chefs/{chef_id}/schedule")
async def api_get_chef_schedule(
    chef_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    month: str = Query(..., description="月份 YYYY-MM"),
):
    """获取厨师排期"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await get_chef_schedule(
            chef_id=chef_id,
            month=month,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e), code=404)


@router.post("/calculate-price")
async def api_calculate_price(
    req: CalculatePriceReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """计算大厨到家价格"""
    tenant_id = _get_tenant_id(request)
    result = await calculate_price(
        dishes=[d.model_dump() for d in req.dishes],
        guest_count=req.guest_count,
        distance_km=req.distance_km,
        tenant_id=tenant_id,
        db=db,
    )
    return _ok(result)


@router.put("/bookings/{booking_id}/confirm")
async def api_confirm_booking(
    booking_id: str,
    req: ConfirmBookingReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """确认预约（关联支付单）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await confirm_booking(
            booking_id=booking_id,
            payment_id=req.payment_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/bookings/{booking_id}/start")
async def api_start_service(
    booking_id: str,
    req: StartServiceReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """开始服务（厨师签到）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await start_service(
            booking_id=booking_id,
            chef_id=req.chef_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/bookings/{booking_id}/complete")
async def api_complete_service(
    booking_id: str,
    req: CompleteServiceReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """完成服务（上传出品照片）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await complete_service(
            booking_id=booking_id,
            photos=req.photos,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/bookings/{booking_id}/rate")
async def api_rate_service(
    booking_id: str,
    req: RateServiceReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """评价服务"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await rate_service(
            booking_id=booking_id,
            rating=req.rating,
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/bookings")
async def api_get_booking_history(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    customer_id: str = Query(..., description="顾客ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """获取顾客预约历史"""
    tenant_id = _get_tenant_id(request)
    result = await get_booking_history(
        customer_id=customer_id,
        tenant_id=tenant_id,
        db=db,
        page=page,
        size=size,
    )
    return _ok(result)
