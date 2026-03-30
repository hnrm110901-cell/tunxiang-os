"""移动收银台操作 API — 服务员手机端(web-crew)的扩展操作

对标：天财商龙移动收银台 8 大快捷操作 + Toast Go 2

端点清单：
  PUT  /api/v1/mobile/orders/{id}/table-info   — 修改开台信息(人数/服务员)
  PUT  /api/v1/mobile/dishes/{id}/availability  — 沽清管理
  PUT  /api/v1/mobile/dishes/{id}/daily-limit   — 限量设置
  PUT  /api/v1/mobile/orders/{id}/waiter        — 修改点菜员
  POST /api/v1/mobile/orders/{id}/copy-dishes   — 从历史订单复制菜品
  GET  /api/v1/mobile/dishes/status             — 刷新菜品沽清/限量状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header，通过 RLS 实现租户隔离。
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/mobile", tags=["mobile-ops"])


# ─── 通用辅助 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request):
    """获取带租户隔离的 DB session"""
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class UpdateTableInfoReq(BaseModel):
    guest_count: Optional[int] = Field(None, ge=1, le=99, description="就餐人数")
    waiter_id: Optional[str] = Field(None, description="服务员ID")


class DishAvailabilityReq(BaseModel):
    available: bool = Field(..., description="true=上架, false=沽清")


class DishDailyLimitReq(BaseModel):
    limit: int = Field(..., ge=0, description="每日限量数，0表示不限")


class UpdateWaiterReq(BaseModel):
    new_waiter_id: str = Field(..., min_length=1, description="新服务员ID")


class CopyDishesReq(BaseModel):
    source_order_id: str = Field(..., min_length=1, description="源订单ID")


# ─── 1. 修改开台信息 ───


@router.put("/orders/{order_id}/table-info")
async def update_table_info(
    order_id: str,
    body: UpdateTableInfoReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """修改已开台订单的人数或服务员

    至少需提供 guest_count 或 waiter_id 之一。
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    if body.guest_count is None and body.waiter_id is None:
        raise HTTPException(status_code=400, detail="至少需要提供 guest_count 或 waiter_id")

    try:
        from ..services.cashier_engine import CashierEngine
        engine = CashierEngine(db, tenant_id)
        result = await engine.update_table_info(
            order_id=order_id,
            guest_count=body.guest_count,
            waiter_id=body.waiter_id,
        )
        await db.commit()
        log.info("update_table_info_ok", guest_count=body.guest_count, waiter_id=body.waiter_id)
        return _ok(result)
    except ValueError as exc:
        log.warning("update_table_info_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 2. 沽清管理 ───


@router.put("/dishes/{dish_id}/availability")
async def set_dish_availability(
    dish_id: str,
    body: DishAvailabilityReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """设置菜品沽清/上架状态"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(dish_id=dish_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import update
        from shared.ontology.src.entities import Dish

        await db.execute(
            update(Dish)
            .where(Dish.id == dish_id, Dish.tenant_id == tenant_id)
            .values(sold_out=not body.available)
        )
        await db.commit()
        log.info("dish_availability_updated", available=body.available)
        return _ok({"dish_id": dish_id, "available": body.available})
    except ValueError as exc:
        log.warning("dish_availability_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 3. 限量设置 ───


@router.put("/dishes/{dish_id}/daily-limit")
async def set_dish_daily_limit(
    dish_id: str,
    body: DishDailyLimitReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """设置菜品每日限量数（0 = 不限量）"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(dish_id=dish_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import update
        from shared.ontology.src.entities import Dish

        await db.execute(
            update(Dish)
            .where(Dish.id == dish_id, Dish.tenant_id == tenant_id)
            .values(daily_limit=body.limit)
        )
        await db.commit()
        log.info("dish_daily_limit_updated", limit=body.limit)
        return _ok({"dish_id": dish_id, "daily_limit": body.limit})
    except ValueError as exc:
        log.warning("dish_daily_limit_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 4. 修改点菜员 ───


@router.put("/orders/{order_id}/waiter")
async def update_order_waiter(
    order_id: str,
    body: UpdateWaiterReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更换订单的点菜服务员"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import update
        from shared.ontology.src.entities import Order

        await db.execute(
            update(Order)
            .where(Order.id == order_id, Order.tenant_id == tenant_id)
            .values(waiter_id=body.new_waiter_id)
        )
        await db.commit()
        log.info("order_waiter_updated", new_waiter_id=body.new_waiter_id)
        return _ok({"order_id": order_id, "waiter_id": body.new_waiter_id})
    except ValueError as exc:
        log.warning("order_waiter_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 5. 复制菜品 ───


@router.post("/orders/{order_id}/copy-dishes")
async def copy_dishes_from_order(
    order_id: str,
    body: CopyDishesReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """从源订单复制全部菜品到当前订单"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, source=body.source_order_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select
        from shared.ontology.src.entities import OrderItem

        # 查询源订单的所有菜品
        source_items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == body.source_order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        source_items = source_items_result.scalars().all()

        if not source_items:
            raise ValueError("源订单无菜品或不存在")

        # 复制到目标订单
        copied_count = 0
        for item in source_items:
            import uuid
            new_item = OrderItem(
                id=str(uuid.uuid4()),
                order_id=order_id,
                tenant_id=tenant_id,
                dish_id=item.dish_id,
                dish_name=item.dish_name,
                quantity=item.quantity,
                unit_price_fen=item.unit_price_fen,
                special_notes=item.special_notes,
            )
            db.add(new_item)
            copied_count += 1

        await db.commit()
        log.info("copy_dishes_ok", copied_count=copied_count)
        return _ok({"order_id": order_id, "copied_count": copied_count})
    except ValueError as exc:
        log.warning("copy_dishes_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 6. 刷新菜品沽清/限量状态 ───


@router.get("/dishes/status")
async def refresh_dish_status(
    request: Request,
    store_id: str,
    db: AsyncSession = Depends(_get_db_session),
):
    """批量获取菜品的沽清和限量状态"""
    tenant_id = _get_tenant_id(request)

    try:
        from sqlalchemy import select
        from shared.ontology.src.entities import Dish

        result = await db.execute(
            select(
                Dish.id,
                Dish.sold_out,
                Dish.daily_limit,
                Dish.daily_sold_count,
            ).where(
                Dish.tenant_id == tenant_id,
                Dish.store_id == store_id,
                Dish.is_deleted == False,  # noqa: E712
            )
        )
        rows = result.all()

        items = []
        for row in rows:
            items.append({
                "dish_id": row.id,
                "sold_out": row.sold_out,
                "daily_limit": getattr(row, "daily_limit", 0) or 0,
                "daily_sold_count": getattr(row, "daily_sold_count", 0) or 0,
            })

        return _ok({"items": items, "total": len(items)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
