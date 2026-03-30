"""自助点餐 API -- 7端点

AI推荐/套餐组合/最优优惠/AA分摊/制作进度/最近门店/等待时间
所有路由需要 X-Tenant-ID header。
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.self_order_engine import (
    ai_recommend_dishes,
    calculate_aa_split,
    calculate_combo_suggestion,
    estimate_wait_time,
    find_best_deal,
    get_nearest_stores,
    track_preparation,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/self-order", tags=["self-order"])


# ── 请求模型 ──────────────────────────────────────────────────

class RecommendRequest(BaseModel):
    store_id: str
    customer_id: Optional[str] = None
    guest_count: int = Field(default=1, ge=1, le=30)
    time_slot: Optional[str] = None
    weather: Optional[str] = None


class ComboRequest(BaseModel):
    store_id: str
    guest_count: int = Field(default=1, ge=1, le=30)
    budget_fen: int = Field(gt=0)


class CartItem(BaseModel):
    dish_id: str
    price_fen: int
    quantity: int = 1


class CouponInfo(BaseModel):
    coupon_id: str
    type: str
    threshold_fen: int = 0
    discount_fen: int = 0
    discount_rate: float = 1.0


class BestDealRequest(BaseModel):
    cart_items: list[CartItem]
    available_coupons: list[CouponInfo] = []


class AASplitRequest(BaseModel):
    split_count: int = Field(ge=1, le=50)


class NearestStoresRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=10.0, ge=0.1, le=50.0)


# ── 1. AI 智能推荐 ───────────────────────────────────────────

@router.post("/recommend")
async def recommend_dishes(
    body: RecommendRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """AI推荐菜品（历史偏好+人数+时段+天气+高毛利权重）"""
    result = await ai_recommend_dishes(
        customer_id=body.customer_id,
        guest_count=body.guest_count,
        time_slot=body.time_slot,
        weather=body.weather,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 2. 套餐智能组合 ─────────────────────────────────────────

@router.post("/combo")
async def combo_suggestion(
    body: ComboRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """套餐智能组合（按人数自动推荐）"""
    result = await calculate_combo_suggestion(
        guest_count=body.guest_count,
        budget_fen=body.budget_fen,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 3. 最优优惠方案 ─────────────────────────────────────────

@router.post("/best-deal")
async def best_deal(
    body: BestDealRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """最优优惠方案（自动选择最划算的券组合）"""
    result = await find_best_deal(
        cart_items=[c.model_dump() for c in body.cart_items],
        available_coupons=[c.model_dump() for c in body.available_coupons],
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 4. AA 分摊 ──────────────────────────────────────────────

@router.post("/orders/{order_id}/aa-split")
async def aa_split(
    order_id: str,
    body: AASplitRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """AA分摊计算（均分+按菜分）"""
    result = await calculate_aa_split(
        order_id=order_id,
        split_count=body.split_count,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 5. 制作进度 ─────────────────────────────────────────────

@router.get("/orders/{order_id}/preparation")
async def preparation_progress(
    order_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """制作进度追踪（5步: received->preparing->cooking->plating->ready）"""
    result = await track_preparation(
        order_id=order_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 6. GPS 最近门店 ─────────────────────────────────────────

@router.post("/nearest-stores")
async def nearest_stores(
    body: NearestStoresRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """GPS最近门店（距离排序+营业状态+等位时间）"""
    result = await get_nearest_stores(
        lat=body.lat,
        lng=body.lng,
        radius_km=body.radius_km,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 7. 预计等待时间 ─────────────────────────────────────────

@router.get("/stores/{store_id}/wait-time")
async def wait_time(
    store_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预计等待时间（基于当前订单量+历史出餐速度）"""
    result = await estimate_wait_time(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}
