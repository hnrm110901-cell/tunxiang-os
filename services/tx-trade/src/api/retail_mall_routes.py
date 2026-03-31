"""零售商城 API — 商品管理 / 订单 / 退款 / 统计

所有接口需要 X-Tenant-ID 和 X-Store-ID header。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services import retail_mall as retail_mall_svc

router = APIRouter(prefix="/api/v1/retail", tags=["retail-mall"])


# ── 请求/响应模型 ─────────────────────────────────────────────


class CreateProductReq(BaseModel):
    name: str = Field(..., max_length=200)
    sku: str = Field(..., max_length=100)
    category: str = Field(default="merchandise", max_length=50)
    price_fen: int = Field(..., gt=0)
    cost_fen: int = Field(default=0, ge=0)
    stock_qty: int = Field(default=0, ge=0)
    min_stock: int = Field(default=0, ge=0)
    image_url: Optional[str] = None
    is_weighable: bool = False


class UpdateProductReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    sku: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=50)
    price_fen: Optional[int] = Field(default=None, gt=0)
    cost_fen: Optional[int] = Field(default=None, ge=0)
    stock_qty: Optional[int] = Field(default=None, ge=0)
    min_stock: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    status: Optional[str] = None
    is_weighable: Optional[bool] = None


class OrderItemReq(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)


class CreateRetailOrderReq(BaseModel):
    items: list[OrderItemReq] = Field(..., min_length=1)
    customer_id: Optional[str] = None
    payment_method: Optional[str] = None


# ── 1. 商品列表 ──────────────────────────────────────────────


@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None, description="分类: seafood_gift/prepared_dish/seasoning/merchandise"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_store_id: str = Header(..., alias="X-Store-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """零售商品列表 — 分页 + 分类筛选"""
    try:
        data = await retail_mall_svc.list_products(
            tenant_id=x_tenant_id,
            store_id=x_store_id,
            db=db,
            category=category,
            page=page,
            size=size,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 2. 创建商品 ──────────────────────────────────────────────


@router.post("/products")
async def create_product(
    body: CreateProductReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_store_id: str = Header(..., alias="X-Store-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建零售商品"""
    try:
        data = await retail_mall_svc.create_product(
            tenant_id=x_tenant_id,
            store_id=x_store_id,
            data=body.model_dump(exclude_none=True),
            db=db,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 3. 更新商品 ──────────────────────────────────────────────


@router.put("/products/{product_id}")
async def update_product(
    product_id: str,
    body: UpdateProductReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新零售商品"""
    try:
        data = await retail_mall_svc.update_product(
            tenant_id=x_tenant_id,
            product_id=product_id,
            data=body.model_dump(exclude_none=True),
            db=db,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 4. 创建零售订单 ──────────────────────────────────────────


@router.post("/orders")
async def create_retail_order(
    body: CreateRetailOrderReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_store_id: str = Header(..., alias="X-Store-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建零售订单 — 含库存扣减，SELECT FOR UPDATE 防超卖"""
    try:
        items = [item.model_dump() for item in body.items]
        data = await retail_mall_svc.create_retail_order(
            tenant_id=x_tenant_id,
            store_id=x_store_id,
            items=items,
            db=db,
            customer_id=body.customer_id,
            payment_method=body.payment_method,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 5. 查询订单详情 ──────────────────────────────────────────


@router.get("/orders/{order_id}")
async def get_retail_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询零售订单详情"""
    try:
        data = await retail_mall_svc.get_retail_order(
            tenant_id=x_tenant_id,
            order_id=order_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── 6. 退款 ──────────────────────────────────────────────────


@router.post("/orders/{order_id}/refund")
async def refund_retail_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """退款零售订单 — 恢复库存"""
    try:
        data = await retail_mall_svc.refund_retail_order(
            tenant_id=x_tenant_id,
            order_id=order_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 7. 零售统计 ──────────────────────────────────────────────


@router.get("/stats")
async def get_retail_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_store_id: str = Header(..., alias="X-Store-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """零售统计 — GMV / 订单量 / 畅销品 Top 10"""
    data = await retail_mall_svc.get_retail_stats(
        tenant_id=x_tenant_id,
        store_id=x_store_id,
        db=db,
    )
    return {"ok": True, "data": data}
