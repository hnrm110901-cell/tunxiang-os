"""会员等级智能调度 API 端点

7 个端点：个性化首页、等级菜单、排队调度、个性化优惠、预订调度、应用等级权益、升级机会
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.smart_dispatcher import (
    apply_level_benefits,
    check_upgrade_opportunity,
    dispatch_menu,
    dispatch_offer,
    dispatch_queue,
    dispatch_reservation,
    get_personalized_home,
)

router = APIRouter(prefix="/api/v1/member/dispatch", tags=["member-dispatch"])


# ── 请求模型 ──────────────────────────────────────────────────


class ReservationRequest(BaseModel):
    customer_id: str
    store_id: str
    party_size: int = Field(ge=1, le=50, default=2)
    date: str
    time: str = ""
    room_preference: str = ""


class ApplyBenefitsRequest(BaseModel):
    customer_id: str
    order_id: str


# ── 1. 个性化首页 ────────────────────────────────────────────


@router.get("/home/{customer_id}")
async def get_personalized_home_route(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按等级+历史+场景定制个性化首页"""
    try:
        data = await get_personalized_home(customer_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 2. 等级菜单 ──────────────────────────────────────────────


@router.get("/menu/{customer_id}/{store_id}")
async def get_level_menu(
    customer_id: str,
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按等级展示专属菜品/价格"""
    try:
        data = await dispatch_menu(customer_id, store_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 3. 排队调度 ──────────────────────────────────────────────


@router.get("/queue/{customer_id}/{store_id}")
async def get_queue_dispatch(
    customer_id: str,
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """VIP 快速通道排队调度"""
    try:
        data = await dispatch_queue(customer_id, store_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 4. 个性化优惠 ────────────────────────────────────────────


@router.get("/offers/{customer_id}")
async def get_personalized_offers(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按等级推送个性化优惠"""
    try:
        data = await dispatch_offer(customer_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 5. 预订调度 ──────────────────────────────────────────────


@router.post("/reservation")
async def create_reservation_dispatch(
    body: ReservationRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """高等级会员优先分配包厢"""
    try:
        data = await dispatch_reservation(
            customer_id=body.customer_id,
            request=body.model_dump(),
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 6. 应用等级权益 ──────────────────────────────────────────


@router.post("/apply-benefits")
async def apply_benefits(
    body: ApplyBenefitsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """自动应用等级权益到订单（无需用户操作）"""
    try:
        data = await apply_level_benefits(body.customer_id, body.order_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 7. 升级机会 ──────────────────────────────────────────────


@router.get("/upgrade/{customer_id}")
async def get_upgrade_opportunity_route(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """升级机会检测: 购物车/结账页面的升级激励"""
    try:
        data = await check_upgrade_opportunity(customer_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
