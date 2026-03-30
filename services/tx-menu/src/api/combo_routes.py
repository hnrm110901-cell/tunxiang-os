"""套餐组合 API — 3个端点

- GET  /api/v1/menu/combos              列出套餐
- POST /api/v1/menu/combos              创建套餐
- POST /api/v1/menu/combos/{combo_id}/order  点套餐→自动展开为多条 OrderItem
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Order, OrderItem, Dish
from shared.ontology.src.enums import OrderStatus
from ..models.dish_combo import DishCombo

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu", tags=["combo"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───

class ComboItemReq(BaseModel):
    dish_id: str
    dish_name: str
    qty: int = Field(default=1, ge=1)
    price_fen: int = Field(ge=0, description="子项售价(分)")


class CreateComboReq(BaseModel):
    store_id: Optional[str] = None
    combo_name: str
    combo_price_fen: int = Field(ge=0)
    original_price_fen: int = Field(ge=0)
    items: list[ComboItemReq]
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool = True


class OrderComboReq(BaseModel):
    order_id: str
    qty: int = Field(default=1, ge=1, description="套餐份数")
    notes: Optional[str] = None


# ─── 端点 ───

@router.get("/combos")
async def list_combos(
    request: Request,
    store_id: Optional[str] = Query(default=None),
    is_active: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出套餐 — 支持按门店和上架状态过滤"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)

    conditions = [
        DishCombo.tenant_id == tenant_uuid,
        DishCombo.is_deleted == False,  # noqa: E712
        DishCombo.is_active == is_active,
    ]
    if store_id:
        conditions.append(DishCombo.store_id == uuid.UUID(store_id))

    result = await db.execute(
        select(DishCombo)
        .where(*conditions)
        .order_by(DishCombo.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    combos = result.scalars().all()

    items = [
        {
            "id": str(c.id),
            "store_id": str(c.store_id) if c.store_id else None,
            "combo_name": c.combo_name,
            "combo_price_fen": c.combo_price_fen,
            "original_price_fen": c.original_price_fen,
            "items": c.items_json,
            "description": c.description,
            "image_url": c.image_url,
            "is_active": c.is_active,
            "saving_fen": c.original_price_fen - c.combo_price_fen,
        }
        for c in combos
    ]

    return _ok({"items": items, "total": len(items), "page": page, "size": size})


@router.post("/combos")
async def create_combo(
    req: CreateComboReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建套餐"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)

    items_json = [
        {
            "dish_id": item.dish_id,
            "dish_name": item.dish_name,
            "qty": item.qty,
            "price_fen": item.price_fen,
        }
        for item in req.items
    ]

    combo = DishCombo(
        id=uuid.uuid4(),
        tenant_id=tenant_uuid,
        store_id=uuid.UUID(req.store_id) if req.store_id else None,
        combo_name=req.combo_name,
        combo_price_fen=req.combo_price_fen,
        original_price_fen=req.original_price_fen,
        items_json=items_json,
        description=req.description,
        image_url=req.image_url,
        is_active=req.is_active,
    )
    db.add(combo)
    await db.commit()

    logger.info(
        "combo_created",
        combo_id=str(combo.id),
        combo_name=req.combo_name,
        items_count=len(items_json),
    )

    return _ok({
        "combo_id": str(combo.id),
        "combo_name": req.combo_name,
        "combo_price_fen": req.combo_price_fen,
        "original_price_fen": req.original_price_fen,
        "saving_fen": req.original_price_fen - req.combo_price_fen,
        "items_count": len(items_json),
    })


@router.post("/combos/{combo_id}/order")
async def order_combo(
    combo_id: str,
    req: OrderComboReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """点套餐 → 自动展开为多条 OrderItem

    每个子菜品按比例分摊套餐价，保留 combo_id 关联。
    """
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    combo_uuid = uuid.UUID(combo_id)
    order_uuid = uuid.UUID(req.order_id)

    # 查套餐
    result = await db.execute(
        select(DishCombo).where(
            DishCombo.id == combo_uuid,
            DishCombo.tenant_id == tenant_uuid,
            DishCombo.is_active == True,  # noqa: E712
        )
    )
    combo = result.scalar_one_or_none()
    if not combo:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")

    # 查订单
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tenant_uuid,
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise HTTPException(status_code=400, detail=f"订单状态 {order.status}，无法加菜")

    # 按比例分摊套餐价到各子项
    combo_items: list[dict] = combo.items_json or []
    original_total = combo.original_price_fen
    combo_total = combo.combo_price_fen

    created_items = []
    total_subtotal = 0

    for idx, ci in enumerate(combo_items):
        ci_price = ci.get("price_fen", 0)
        ci_qty = ci.get("qty", 1) * req.qty

        # 按原价占比分摊套餐价；最后一项用减法兜底，避免分钱误差
        if idx < len(combo_items) - 1 and original_total > 0:
            allocated_unit = round(combo_total * ci_price / original_total)
        elif idx == len(combo_items) - 1:
            # 最后一项 = 套餐总价 - 已分配
            allocated_unit = combo_total * req.qty - total_subtotal
            # 修正为单价
            allocated_unit = allocated_unit // ci_qty if ci_qty > 0 else allocated_unit
        else:
            allocated_unit = ci_price

        subtotal = allocated_unit * ci_qty
        total_subtotal += subtotal

        dish_uuid = uuid.UUID(ci["dish_id"]) if ci.get("dish_id") else None

        # 查菜品获取 BOM 成本
        food_cost_fen = None
        gross_margin = None
        if dish_uuid:
            dish_result = await db.execute(
                select(Dish).where(Dish.id == dish_uuid)
            )
            dish = dish_result.scalar_one_or_none()
            if dish and dish.cost_fen:
                food_cost_fen = dish.cost_fen * ci_qty
                if subtotal > 0:
                    gross_margin = round((subtotal - food_cost_fen) / subtotal, 4)

        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            order_id=order_uuid,
            dish_id=dish_uuid,
            item_name=ci.get("dish_name", "套餐子项"),
            quantity=ci_qty,
            unit_price_fen=allocated_unit,
            subtotal_fen=subtotal,
            food_cost_fen=food_cost_fen,
            gross_margin=gross_margin,
            notes=req.notes or f"套餐[{combo.combo_name}]",
            customizations={"combo_id": combo_id, "combo_name": combo.combo_name},
            pricing_mode="fixed",
        )
        db.add(item)
        created_items.append({
            "item_id": str(item.id),
            "dish_name": ci.get("dish_name"),
            "qty": ci_qty,
            "unit_price_fen": allocated_unit,
            "subtotal_fen": subtotal,
        })

    # 更新订单总额
    combo_subtotal = combo.combo_price_fen * req.qty
    order.total_amount_fen += combo_subtotal
    order.final_amount_fen = order.total_amount_fen - order.discount_amount_fen
    if order.status == OrderStatus.pending.value:
        order.status = OrderStatus.confirmed.value

    await db.commit()

    logger.info(
        "combo_ordered",
        combo_id=combo_id,
        order_id=req.order_id,
        qty=req.qty,
        items_expanded=len(created_items),
        combo_subtotal_fen=combo_subtotal,
    )

    return _ok({
        "combo_id": combo_id,
        "combo_name": combo.combo_name,
        "qty": req.qty,
        "combo_subtotal_fen": combo_subtotal,
        "items_expanded": created_items,
        "order_total_fen": order.total_amount_fen,
        "order_final_fen": order.final_amount_fen,
    })
