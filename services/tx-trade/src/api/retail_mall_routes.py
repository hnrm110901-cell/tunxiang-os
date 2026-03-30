"""甄选商城 API — 6个端点

1. 商品列表（分类筛选）
2. 商品详情
3. 创建零售订单
4. 会员折扣
5. 快递追踪
6. 礼品卡列表
"""
from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/retail", tags=["retail-mall"])


# ── 请求模型 ──────────────────────────────────────────────────

class RetailOrderItemReq(BaseModel):
    product_id: str
    sku_id: str
    quantity: int = Field(ge=1)


class AddressReq(BaseModel):
    name: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class CreateRetailOrderReq(BaseModel):
    customer_id: str
    items: list[RetailOrderItemReq]
    address: AddressReq


class ApplyDiscountReq(BaseModel):
    card_id: str


# ── 1. 商品列表 ──────────────────────────────────────────────

@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None, description="分类: seafood_gift/prepared_dish/seasoning/merchandise"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """甄选商城商品列表 — 海味礼盒/预制菜/调味品/周边"""
    # TODO: 注入真实 DB session 后调用 retail_mall.list_products
    return {
        "ok": True,
        "data": {
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
        },
    }


# ── 2. 商品详情 ──────────────────────────────────────────────

@router.get("/products/{product_id}")
async def get_product_detail(
    product_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """商品详情 — 大图/规格/产地/保质期"""
    # TODO: 注入真实 DB session 后调用 retail_mall.get_product_detail
    return {
        "ok": True,
        "data": {
            "product_id": product_id,
            "name": "placeholder",
            "images": [],
            "skus": [],
            "price_fen": 0,
        },
    }


# ── 3. 创建零售订单 ──────────────────────────────────────────

@router.post("/orders")
async def create_retail_order(
    body: CreateRetailOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """创建零售订单 — 独立于堂食订单系统"""
    # TODO: 注入真实 DB session 后调用 retail_mall.create_retail_order
    return {
        "ok": True,
        "data": {
            "order_id": "placeholder",
            "order_no": "placeholder",
            "customer_id": body.customer_id,
            "total_fen": 0,
            "status": "pending",
            "items": [item.model_dump() for item in body.items],
            "address": body.address.model_dump(),
        },
    }


# ── 4. 会员折扣 ──────────────────────────────────────────────

@router.post("/orders/{order_id}/discount")
async def apply_member_discount(
    order_id: str,
    body: ApplyDiscountReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """会员折扣 — 根据会员卡等级计算零售折扣"""
    # TODO: 注入真实 DB session 后调用 retail_mall.apply_member_discount
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "card_id": body.card_id,
            "original_fen": 0,
            "discount_fen": 0,
            "final_fen": 0,
            "discount_rate": 100,
        },
    }


# ── 5. 快递追踪 ──────────────────────────────────────────────

@router.get("/orders/{order_id}/delivery")
async def track_delivery(
    order_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """快递追踪 — 物流状态+轨迹"""
    # TODO: 注入真实 DB session 后调用 retail_mall.track_delivery
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "status": "pending",
            "express_company": None,
            "tracking_no": None,
            "traces": [],
        },
    }


# ── 6. 礼品卡列表 ────────────────────────────────────────────

@router.get("/gift-cards")
async def list_gift_cards(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """礼品卡列表 — 送礼场景"""
    # TODO: 注入真实 DB session 后调用 retail_mall.get_gift_cards
    return {
        "ok": True,
        "data": {
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
        },
    }
