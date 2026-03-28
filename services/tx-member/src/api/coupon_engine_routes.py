"""优惠券引擎 API — 8端点"""
from typing import Optional
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from services.coupon_engine import (
    CouponType,
    create_coupon,
    batch_issue,
    verify_coupon,
    redeem_coupon,
    check_stacking_rules,
    calculate_discount,
    set_revenue_rule,
    get_coupon_stats,
)

router = APIRouter(prefix="/api/v1/member/coupons", tags=["coupon-engine"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CreateCouponReq(BaseModel):
    coupon_type: str = Field(..., description="券类型: cash/discount/free_item/upgrade/buy_gift/gift/delivery")
    config: dict = Field(default_factory=dict, description="券配置")


class BatchIssueReq(BaseModel):
    coupon_id: str
    target_customers: list[str] = Field(..., min_length=1)


class VerifyCouponReq(BaseModel):
    code: str
    order_id: str = ""


class RedeemCouponReq(BaseModel):
    code: str
    order_id: str


class CouponItem(BaseModel):
    code: str = ""
    coupon_type: str = "cash"
    face_value_fen: int = 0
    discount_rate: int = 100
    min_order_amount_fen: int = 0
    item_dish_id: Optional[str] = None
    upgrade_price_fen: int = 0
    gift_dish_id: Optional[str] = None
    gift_count: int = 0


class CheckStackingReq(BaseModel):
    coupons: list[CouponItem]
    order_id: str = ""


class OrderItemInput(BaseModel):
    dish_id: str
    name: str = ""
    price_fen: int = Field(0, ge=0)
    quantity: int = Field(1, ge=1)


class CalculateDiscountReq(BaseModel):
    coupons: list[CouponItem]
    order: dict = Field(
        ...,
        description="订单: {order_id, total_fen, items: [{dish_id, price_fen, quantity}], delivery_fee_fen}",
    )


class SetRevenueRuleReq(BaseModel):
    coupon_id: str
    config: dict = Field(
        default_factory=dict,
        description="收入规则: {count_as_revenue: bool, revenue_ratio: float}",
    )


class CouponStatsReq(BaseModel):
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/create")
async def api_create_coupon(
    req: CreateCouponReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建券模板"""
    result = await create_coupon(
        coupon_type=req.coupon_type,
        config=req.config,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/batch-issue")
async def api_batch_issue(
    req: BatchIssueReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """批量发放券"""
    result = await batch_issue(
        coupon_id=req.coupon_id,
        target_customers=req.target_customers,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/verify")
async def api_verify_coupon(
    req: VerifyCouponReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """验证券"""
    result = await verify_coupon(
        code=req.code,
        order_id=req.order_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/redeem")
async def api_redeem_coupon(
    req: RedeemCouponReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """核销券"""
    result = await redeem_coupon(
        code=req.code,
        order_id=req.order_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/check-stacking")
async def api_check_stacking(
    req: CheckStackingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """叠加规则检查"""
    coupons_raw = [c.model_dump() for c in req.coupons]
    result = await check_stacking_rules(
        coupons=coupons_raw,
        order_id=req.order_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/calculate-discount")
async def api_calculate_discount(
    req: CalculateDiscountReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """计算优惠金额"""
    coupons_raw = [c.model_dump() for c in req.coupons]
    result = await calculate_discount(
        coupons=coupons_raw,
        order=req.order,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/revenue-rule")
async def api_set_revenue_rule(
    req: SetRevenueRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """设置收入规则"""
    result = await set_revenue_rule(
        coupon_id=req.coupon_id,
        config=req.config,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/stats")
async def api_coupon_stats(
    start_date: str,
    end_date: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """券统计"""
    result = await get_coupon_stats(
        tenant_id=x_tenant_id,
        date_range=(start_date, end_date),
    )
    return {"ok": True, "data": result}
