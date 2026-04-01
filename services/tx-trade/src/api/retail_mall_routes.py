"""甄选商城 API — 8个端点（v103 DB 化版本）

1. GET    /api/v1/retail/products                 商品列表
2. GET    /api/v1/retail/products/{product_id}    商品详情
3. POST   /api/v1/retail/orders                   创建零售订单
4. POST   /api/v1/retail/orders/{id}/discount     会员折扣
5. GET    /api/v1/retail/orders/{id}/delivery      快递追踪
6. GET    /api/v1/retail/gift-cards               礼品卡列表
7. POST   /api/v1/retail/products                 创建商品（后台）
8. PUT    /api/v1/retail/products/{id}/status      商品上下架（后台）
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import retail_mall

router = APIRouter(prefix="/api/v1/retail", tags=["retail-mall"])


async def get_db() -> AsyncSession:  # type: ignore[override]
    raise NotImplementedError("DB session dependency not configured")


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


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


class CreateProductReq(BaseModel):
    name: str
    category: str
    price_fen: int = Field(ge=1)
    original_price_fen: Optional[int] = None
    cover_image: Optional[str] = None
    description: Optional[str] = None
    stock: int = Field(ge=0, default=0)
    tags: list[str] = []
    origin: Optional[str] = None
    shelf_life: Optional[str] = None


class UpdateStatusReq(BaseModel):
    status: str  # on_sale / off_sale / draft


# ── 1. 商品列表 ──────────────────────────────────────────────

@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await retail_mall.list_products(
            category=category, tenant_id=x_tenant_id, db=db, page=page, size=size,
        )
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 2. 商品详情 ──────────────────────────────────────────────

@router.get("/products/{product_id}")
async def get_product_detail(
    product_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await retail_mall.get_product_detail(
        product_id=product_id, tenant_id=x_tenant_id, db=db,
    )
    if not result:
        return error_response("product_not_found")
    return ok_response(result)


# ── 3. 创建零售订单 ──────────────────────────────────────────

@router.post("/orders")
async def create_retail_order(
    body: CreateRetailOrderReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await retail_mall.create_retail_order(
            customer_id=body.customer_id,
            items=[item.model_dump() for item in body.items],
            address=body.address.model_dump(),
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 4. 会员折扣 ──────────────────────────────────────────────

@router.post("/orders/{order_id}/discount")
async def apply_member_discount(
    order_id: str,
    body: ApplyDiscountReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await retail_mall.apply_member_discount(
            order_id=order_id, card_id=body.card_id,
            tenant_id=x_tenant_id, db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 5. 快递追踪 ──────────────────────────────────────────────

@router.get("/orders/{order_id}/delivery")
async def track_delivery(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await retail_mall.track_delivery(
        order_id=order_id, tenant_id=x_tenant_id, db=db,
    )
    return ok_response(result)


# ── 6. 礼品卡列表 ────────────────────────────────────────────

@router.get("/gift-cards")
async def list_gift_cards(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    return ok_response({"items": [], "total": 0, "page": page, "size": size})


# ── 7. 创建商品（后台） ──────────────────────────────────────

@router.post("/products")
async def create_product(
    body: CreateProductReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await retail_mall.create_product(
            name=body.name, category=body.category,
            price_fen=body.price_fen,
            original_price_fen=body.original_price_fen,
            cover_image=body.cover_image,
            description=body.description,
            stock=body.stock, tags=body.tags,
            origin=body.origin, shelf_life=body.shelf_life,
            tenant_id=x_tenant_id, db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 8. 商品上下架 ────────────────────────────────────────────

@router.put("/products/{product_id}/status")
async def update_product_status(
    product_id: str,
    body: UpdateStatusReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await retail_mall.update_product_status(
            product_id=product_id, status=body.status,
            tenant_id=x_tenant_id, db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))
