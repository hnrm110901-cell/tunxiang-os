"""积分商城 API -- 6端点

商品列表/积分兑换/兑换历史/上架商品/成就系统/生日特权
所有路由需要 X-Tenant-ID header。
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.points_mall import (
    check_birthday_privilege,
    create_mall_item,
    exchange_item,
    get_achievement_list,
    get_exchange_history,
    list_mall_items,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/points-mall", tags=["points-mall"])


# ── 请求模型 ──────────────────────────────────────────────────

class ExchangeReq(BaseModel):
    customer_id: str
    item_id: str
    points_cost: int = Field(gt=0)


class CreateMallItemReq(BaseModel):
    name: str
    category: str  # dish | coupon | merchandise
    points_cost: int = Field(gt=0)
    stock: int = Field(ge=0)
    image_url: str = ""
    description: str = ""


# ── 1. 商城商品列表 ─────────────────────────────────────────

@router.get("/items")
async def api_list_mall_items(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """商城商品列表（菜品/周边/优惠券）"""
    result = await list_mall_items(
        category=category,
        tenant_id=x_tenant_id,
        db=db,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result, "error": None}


# ── 2. 积分兑换 ─────────────────────────────────────────────

@router.post("/exchange")
async def api_exchange_item(
    body: ExchangeReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分兑换（扣积分+创建记录+库存-1）"""
    result = await exchange_item(
        customer_id=body.customer_id,
        item_id=body.item_id,
        points_cost=body.points_cost,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 3. 兑换历史 ─────────────────────────────────────────────

@router.get("/exchange-history/{customer_id}")
async def api_exchange_history(
    customer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """兑换历史"""
    result = await get_exchange_history(
        customer_id=customer_id,
        tenant_id=x_tenant_id,
        db=db,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result, "error": None}


# ── 4. 上架商品 ─────────────────────────────────────────────

@router.post("/items")
async def api_create_mall_item(
    body: CreateMallItemReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """上架商品"""
    result = await create_mall_item(
        name=body.name,
        category=body.category,
        points_cost=body.points_cost,
        stock=body.stock,
        image_url=body.image_url,
        tenant_id=x_tenant_id,
        db=db,
        description=body.description,
    )
    return {"ok": True, "data": result, "error": None}


# ── 5. 成就系统 ─────────────────────────────────────────────

@router.get("/achievements/{customer_id}")
async def api_achievements(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """成就系统（消费里程碑+徽章）"""
    result = await get_achievement_list(
        customer_id=customer_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 6. 生日特权 ─────────────────────────────────────────────

@router.get("/birthday/{customer_id}")
async def api_birthday_privilege(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """生日月特权检查"""
    result = await check_birthday_privilege(
        customer_id=customer_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}
