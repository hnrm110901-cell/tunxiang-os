"""券权益与会员识别 API — 9个端点"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services import coupon_service as cs

router = APIRouter(prefix="/api/v1/trade/coupon", tags=["coupon-benefit"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class IdentifyMemberReq(BaseModel):
    phone_or_card: str


class CreateCardReq(BaseModel):
    customer_id: str
    initial_amount_fen: int


class RechargeReq(BaseModel):
    card_id: str
    amount_fen: int
    payment_method: str


class DeductReq(BaseModel):
    card_id: str
    amount_fen: int
    order_id: str


class VerifyCouponReq(BaseModel):
    coupon_code: str
    order_id: str


class RedeemCouponReq(BaseModel):
    coupon_code: str
    order_id: str


class BenefitConflictReq(BaseModel):
    benefits: list[dict]
    order_id: str


class MemberPriceReq(BaseModel):
    dish_id: str
    member_level: str


class CouponAuditReq(BaseModel):
    store_id: str
    start_date: str
    end_date: str


# ─── 端点 ───


@router.post("/identify-member")
async def identify_member(
    body: IdentifyMemberReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """会员识别"""
    tenant_id = _get_tenant_id(request)
    result = await cs.identify_member(
        phone_or_card=body.phone_or_card,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/stored-value/create")
async def create_stored_value_card(
    body: CreateCardReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """储值卡开卡"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await cs.create_stored_value_card(
            customer_id=body.customer_id,
            initial_amount_fen=body.initial_amount_fen,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stored-value/recharge")
async def recharge(
    body: RechargeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """储值充值"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await cs.recharge(
            card_id=body.card_id,
            amount_fen=body.amount_fen,
            payment_method=body.payment_method,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stored-value/deduct")
async def deduct_stored_value(
    body: DeductReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """储值消费"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await cs.deduct_stored_value(
            card_id=body.card_id,
            amount_fen=body.amount_fen,
            order_id=body.order_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify")
async def verify_coupon(
    body: VerifyCouponReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """券验证"""
    tenant_id = _get_tenant_id(request)
    result = await cs.verify_coupon(
        coupon_code=body.coupon_code,
        order_id=body.order_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/redeem")
async def redeem_coupon(
    body: RedeemCouponReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """券核销"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await cs.redeem_coupon(
            coupon_code=body.coupon_code,
            order_id=body.order_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/check-conflict")
async def check_benefit_conflict(
    body: BenefitConflictReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """权益冲突校验"""
    tenant_id = _get_tenant_id(request)
    result = await cs.check_benefit_conflict(
        benefits=body.benefits,
        order_id=body.order_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/member-price")
async def calculate_member_price(
    body: MemberPriceReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """会员价计算"""
    tenant_id = _get_tenant_id(request)
    result = await cs.calculate_member_price(
        dish_id=body.dish_id,
        member_level=body.member_level,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/audit")
async def get_coupon_audit(
    body: CouponAuditReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """券核销审计"""
    tenant_id = _get_tenant_id(request)
    result = await cs.get_coupon_audit(
        store_id=body.store_id,
        date_range=(body.start_date, body.end_date),
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}
