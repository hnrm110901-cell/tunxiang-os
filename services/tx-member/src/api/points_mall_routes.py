"""积分商城 API — 18 个端点

路由前缀：/api/v1/member/points-mall
所有路由需要 X-Tenant-ID header。

端点列表：
  GET  /products               商品列表（会员端，支持scope过滤）
  GET  /products/{id}          商品详情
  POST /products               新增商品（管理端）
  PUT  /products/{id}          更新商品（管理端）
  POST /redeem                 积分兑换
  GET  /orders                 我的兑换记录
  GET  /orders/{id}            订单详情
  POST /orders/{id}/fulfill    核销（门店）
  POST /orders/{id}/cancel     取消订单
  GET  /stats                  商城统计（管理端）
  # v345 新增
  GET  /categories             分类列表
  POST /categories             新增分类
  PUT  /categories/{id}        更新分类
  DELETE /categories/{id}      删除分类
  GET  /achievements           成就列表（从DB读取）
  POST /achievements/seed      初始化默认成就配置
  POST /orders/{id}/ship       实物发货
  POST /orders/{id}/deliver    确认收货
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.points_mall_v2 import (
    cancel_order,
    confirm_delivery,
    create_category,
    create_product,
    delete_category,
    fulfill_order,
    get_achievement_list,
    get_customer_orders,
    get_order_detail,
    get_order_stats,
    get_product,
    list_categories,
    list_products,
    redeem,
    seed_default_achievements,
    ship_order,
    update_category,
    update_product,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member/points-mall", tags=["points-mall"])


# ── 工具函数 ──────────────────────────────────────────────────


def _require_tenant(x_tenant_id: str) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


# ── 请求/响应模型 ─────────────────────────────────────────────


class CreateProductReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    product_type: str = Field(..., description="physical | coupon | dish | stored_value")
    points_required: int = Field(..., gt=0, description="所需积分（正整数）")
    product_content: dict = Field(default_factory=dict, description="商品内容（JSONB）")
    description: Optional[str] = None
    image_url: Optional[str] = None
    stock: int = Field(default=-1, ge=-1, description="-1=不限库存")
    limit_per_customer: int = Field(default=0, ge=0)
    limit_per_period: int = Field(default=0, ge=0)
    limit_period_days: int = Field(default=30, ge=1)
    sort_order: int = Field(default=0, ge=0)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class UpdateProductReq(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    image_url: Optional[str] = None
    points_required: Optional[int] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=-1)
    limit_per_customer: Optional[int] = Field(None, ge=0)
    limit_per_period: Optional[int] = Field(None, ge=0)
    limit_period_days: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(None, ge=0)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    product_content: Optional[dict] = None


class RedeemReq(BaseModel):
    product_id: str = Field(..., description="商品 UUID")
    customer_id: str = Field(..., description="顾客 UUID")
    quantity: int = Field(default=1, ge=1, description="兑换数量")
    store_id: Optional[str] = Field(None, description="兑换门店 UUID（实物必填）")
    delivery_address: Optional[str] = Field(None, max_length=500)
    delivery_name: Optional[str] = Field(None, max_length=50)
    delivery_phone: Optional[str] = Field(None, max_length=20)


class FulfillOrderReq(BaseModel):
    operator_id: str = Field(..., description="操作员 UUID（门店核销人员）")


class CancelOrderReq(BaseModel):
    cancel_reason: str = Field(..., min_length=1, max_length=200, description="取消原因")


class CreateCategoryReq(BaseModel):
    category_name: str = Field(..., min_length=1, max_length=50, description="分类名称")
    category_code: str = Field(..., min_length=1, max_length=30, description="分类编码")
    icon_url: Optional[str] = Field(None, max_length=500)
    sort_order: int = Field(default=0, ge=0)


class UpdateCategoryReq(BaseModel):
    category_name: Optional[str] = Field(None, min_length=1, max_length=50)
    icon_url: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ShipOrderReq(BaseModel):
    carrier: str = Field(..., min_length=1, max_length=50, description="快递公司")
    tracking_no: str = Field(..., min_length=1, max_length=100, description="快递单号")
    operator_id: Optional[str] = Field(None, description="操作员 UUID")


# ── 1. 商品列表（会员端）────────────────────────────────────


@router.get("/products")
async def api_list_products(
    customer_id: Optional[str] = Query(None, description="顾客 UUID，用于查询已兑次数"),
    product_type: Optional[str] = Query(None, description="physical | coupon | dish | stored_value"),
    category_id: Optional[str] = Query(None, description="分类 UUID"),
    store_id: Optional[str] = Query(None, description="当前门店 UUID（用于scope过滤）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分商城商品列表（有效商品，按排序权重 ASC，支持scope过滤）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await list_products(
            tenant_id=tenant_id,
            db=db,
            customer_id=customer_id,
            product_type=product_type,
            category_id=category_id,
            store_id=store_id,
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 2. 商品详情 ──────────────────────────────────────────────


@router.get("/products/{product_id}")
async def api_get_product(
    product_id: str,
    customer_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """商品详情 + 库存余量 + 当前客户已兑次数"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await get_product(
            product_id=product_id,
            tenant_id=tenant_id,
            db=db,
            customer_id=customer_id,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "product_not_found" else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 3. 新增商品（管理端）────────────────────────────────────


@router.post("/products")
async def api_create_product(
    body: CreateProductReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新增积分商城商品（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await create_product(
            name=body.name,
            product_type=body.product_type,
            points_required=body.points_required,
            product_content=body.product_content,
            tenant_id=tenant_id,
            db=db,
            description=body.description,
            image_url=body.image_url,
            stock=body.stock,
            limit_per_customer=body.limit_per_customer,
            limit_per_period=body.limit_per_period,
            limit_period_days=body.limit_period_days,
            sort_order=body.sort_order,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 4. 更新商品（管理端）────────────────────────────────────


@router.put("/products/{product_id}")
async def api_update_product(
    product_id: str,
    body: UpdateProductReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新商城商品（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await update_product(
            product_id=product_id,
            tenant_id=tenant_id,
            db=db,
            name=body.name,
            description=body.description,
            image_url=body.image_url,
            points_required=body.points_required,
            stock=body.stock,
            limit_per_customer=body.limit_per_customer,
            limit_per_period=body.limit_per_period,
            limit_period_days=body.limit_period_days,
            is_active=body.is_active,
            sort_order=body.sort_order,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            product_content=body.product_content,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "product_not_found" else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 5. 积分兑换 ──────────────────────────────────────────────


@router.post("/redeem")
async def api_redeem(
    body: RedeemReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分兑换

    原子事务：扣积分 → 扣库存 → 建订单 → 发放内容（优惠券/储值金立即发放，实物/菜品待核销）
    """
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await redeem(
            product_id=body.product_id,
            customer_id=body.customer_id,
            tenant_id=tenant_id,
            db=db,
            store_id=body.store_id,
            quantity=body.quantity,
            delivery_address=body.delivery_address,
            delivery_name=body.delivery_name,
            delivery_phone=body.delivery_phone,
        )
    except ValueError as exc:
        code = str(exc)
        status_map = {
            "product_not_found": 404,
            "member_card_not_found": 404,
            "order_not_found": 404,
            "insufficient_points": 422,
            "insufficient_stock": 422,
            "redeem_limit_exceeded": 422,
            "product_not_active": 422,
            "product_expired": 422,
            "product_not_started": 422,
        }
        http_status = status_map.get(code.split(":")[0], 400)
        raise HTTPException(status_code=http_status, detail=code)
    return _ok(result)


# ── 6. 我的兑换记录 ──────────────────────────────────────────


@router.get("/orders")
async def api_get_customer_orders(
    customer_id: str = Query(..., description="顾客 UUID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询客户的兑换记录（分页，按创建时间倒序）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await get_customer_orders(
            customer_id=customer_id,
            tenant_id=tenant_id,
            db=db,
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 7. 订单详情 ──────────────────────────────────────────────


@router.get("/orders/{order_id}")
async def api_get_order_detail(
    order_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """兑换订单详情"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await get_order_detail(
            order_id=order_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "order_not_found" else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 8. 核销订单（门店）──────────────────────────────────────


@router.post("/orders/{order_id}/fulfill")
async def api_fulfill_order(
    order_id: str,
    body: FulfillOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店核销 — 将 pending 订单标记为 fulfilled（实物/菜品发货/出餐后调用）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await fulfill_order(
            order_id=order_id,
            operator_id=body.operator_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 422
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 9. 取消订单 ──────────────────────────────────────────────


@router.post("/orders/{order_id}/cancel")
async def api_cancel_order(
    order_id: str,
    body: CancelOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """取消兑换订单（退还积分 + 退还库存，仅限 pending 状态）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await cancel_order(
            order_id=order_id,
            cancel_reason=body.cancel_reason,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 422
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 10. 商城统计（管理端）───────────────────────────────────


@router.get("/stats")
async def api_get_order_stats(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """商城数据统计：总兑换次数、总消耗积分、各商品兑换排名 TOP 20（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await get_order_stats(
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ══════════════════════════════════════════════════════════════════
#  v345 新增端点
# ══════════════════════════════════════════════════════════════════


# ── 11. 分类列表 ─────────────────────────────────────────────


@router.get("/categories")
async def api_list_categories(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分商城分类列表"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await list_categories(tenant_id=tenant_id, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 12. 新增分类 ─────────────────────────────────────────────


@router.post("/categories")
async def api_create_category(
    body: CreateCategoryReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新增积分商城分类（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await create_category(
            category_name=body.category_name,
            category_code=body.category_code,
            tenant_id=tenant_id,
            db=db,
            icon_url=body.icon_url,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        code = str(exc)
        status = 409 if "duplicate" in code else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 13. 更新分类 ─────────────────────────────────────────────


@router.put("/categories/{category_id}")
async def api_update_category(
    category_id: str,
    body: UpdateCategoryReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新分类（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await update_category(
            category_id=category_id,
            tenant_id=tenant_id,
            db=db,
            category_name=body.category_name,
            icon_url=body.icon_url,
            sort_order=body.sort_order,
            is_active=body.is_active,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 14. 删除分类 ─────────────────────────────────────────────


@router.delete("/categories/{category_id}")
async def api_delete_category(
    category_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """删除分类（软删除，管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await delete_category(
            category_id=category_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 400
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 15. 成就列表 ─────────────────────────────────────────────


@router.get("/achievements")
async def api_get_achievements(
    customer_id: str = Query(..., description="顾客 UUID"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """成就列表（从DB配置读取，含进度和已获得状态）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await get_achievement_list(
            customer_id=customer_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 16. 初始化默认成就 ───────────────────────────────────────


@router.post("/achievements/seed")
async def api_seed_achievements(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """初始化默认6个成就配置（幂等，管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await seed_default_achievements(
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ok(result)


# ── 17. 实物发货 ─────────────────────────────────────────────


@router.post("/orders/{order_id}/ship")
async def api_ship_order(
    order_id: str,
    body: ShipOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """实物发货 — 填写快递信息，fulfillment_status: pending -> shipped"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await ship_order(
            order_id=order_id,
            carrier=body.carrier,
            tracking_no=body.tracking_no,
            tenant_id=tenant_id,
            db=db,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 422
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)


# ── 18. 确认收货 ─────────────────────────────────────────────


@router.post("/orders/{order_id}/deliver")
async def api_confirm_delivery(
    order_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """确认收货 — fulfillment_status: shipped -> delivered, status -> fulfilled"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        result = await confirm_delivery(
            order_id=order_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if "not_found" in code else 422
        raise HTTPException(status_code=status, detail=code)
    return _ok(result)
