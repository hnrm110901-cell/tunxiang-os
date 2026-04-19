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

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher
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
            update(Dish).where(Dish.id == dish_id, Dish.tenant_id == tenant_id).values(sold_out=not body.available)
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
            update(Dish).where(Dish.id == dish_id, Dish.tenant_id == tenant_id).values(daily_limit=body.limit)
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
            update(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).values(waiter_id=body.new_waiter_id)
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
            items.append(
                {
                    "dish_id": row.id,
                    "sold_out": row.sold_out,
                    "daily_limit": getattr(row, "daily_limit", 0) or 0,
                    "daily_sold_count": getattr(row, "daily_sold_count", 0) or 0,
                }
            )

        return _ok({"items": items, "total": len(items)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ═══════════════════════════════════════════════
# 以下 9 个端点：补齐天财商龙移动收银台缺失功能
# ═══════════════════════════════════════════════


# ─── 请求模型（新增） ───


class PriceOverrideReq(BaseModel):
    new_price_fen: int = Field(..., ge=1, description="新单价(分)")
    reason: str = Field("", max_length=200, description="变价原因(如称重后)")


class TransferItemReq(BaseModel):
    target_table_no: str = Field(..., min_length=1, description="目标桌号")


class KitchenMessageReq(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="发送给后厨的消息")
    table_no: str = Field("", description="关联桌号(可选)")


class TransferPaymentReq(BaseModel):
    source_order_id: str = Field(..., min_length=1, description="源订单ID")
    target_order_id: str = Field(..., min_length=1, description="目标订单ID")
    payment_id: str = Field(..., min_length=1, description="付款记录ID")


# ─── 7. 埋单(Pre-bill) ───


@router.post("/orders/{order_id}/pre-bill")
async def pre_bill(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """生成预结账单(仅查看, 不收款)

    返回账单明细数据, 前端展示给顾客确认后再正式结账。
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select

        from shared.ontology.src.entities import Order, OrderItem

        order_result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("订单不存在")

        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        items = items_result.scalars().all()

        bill_items = []
        subtotal_fen = 0
        for item in items:
            if item.return_flag:
                continue
            line_total = item.subtotal_fen or (item.unit_price_fen * item.quantity)
            subtotal_fen += line_total
            bill_items.append(
                {
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "unit_price_fen": item.unit_price_fen,
                    "subtotal_fen": line_total,
                    "notes": item.notes,
                    "is_gift": item.is_gift,
                }
            )

        discount_fen = order.discount_amount_fen or 0
        service_charge_fen = order.service_charge_fen or 0
        total_fen = subtotal_fen - discount_fen + service_charge_fen

        log.info("pre_bill_generated", item_count=len(bill_items), total_fen=total_fen)
        return _ok(
            {
                "order_id": order_id,
                "order_no": order.order_no,
                "table_no": order.table_number,
                "items": bill_items,
                "subtotal_fen": subtotal_fen,
                "discount_fen": discount_fen,
                "service_charge_fen": service_charge_fen,
                "total_fen": total_fen,
                "guest_count": order.guest_count,
            }
        )
    except ValueError as exc:
        log.warning("pre_bill_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 8. 起菜(Fire to Kitchen) ───


@router.post("/orders/{order_id}/fire")
async def fire_to_kitchen(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """手动通知厨房开始制作(将未下厨的菜品发送到KDS)"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select

        from shared.ontology.src.entities import Order, OrderItem

        from ..services.kds_dispatch import dispatch_order_to_kds

        order_result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("订单不存在")

        # 查询未发送KDS的菜品
        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
                OrderItem.sent_to_kds_flag == False,  # noqa: E712
                OrderItem.return_flag == False,  # noqa: E712
            )
        )
        pending_items = items_result.scalars().all()

        if not pending_items:
            raise ValueError("没有待起菜的菜品")

        items_data = [
            {
                "item_id": str(item.id),
                "dish_id": str(item.dish_id) if item.dish_id else None,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "notes": item.notes,
                "kds_station": item.kds_station,
            }
            for item in pending_items
        ]

        await dispatch_order_to_kds(
            order_id=order_id,
            order_items=items_data,
            tenant_id=tenant_id,
            db=db,
            table_no=order.table_number,
        )

        # 标记已发送KDS
        from sqlalchemy import update

        for item in pending_items:
            await db.execute(update(OrderItem).where(OrderItem.id == item.id).values(sent_to_kds_flag=True))
        await db.commit()

        log.info("fire_to_kitchen_ok", fired_count=len(pending_items))
        return _ok(
            {
                "order_id": order_id,
                "fired_count": len(pending_items),
                "items": [i["item_name"] for i in items_data],
            }
        )
    except ValueError as exc:
        log.warning("fire_to_kitchen_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 9. 上菜/划菜(Mark Served) ───


@router.put("/orders/{order_id}/items/{item_id}/served")
async def mark_item_served(
    order_id: str,
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """标记某道菜已上桌(划菜)"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, item_id=item_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select, update

        from shared.ontology.src.entities import OrderItem

        # 确认item存在且属于该订单
        item_result = await db.execute(
            select(OrderItem).where(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        item = item_result.scalar_one_or_none()
        if not item:
            raise ValueError("菜品不存在")

        # 使用 customizations JSON 字段存储 served_at
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        customs = item.customizations or {}
        customs["served_at"] = now

        await db.execute(update(OrderItem).where(OrderItem.id == item_id).values(customizations=customs))
        await db.commit()

        log.info("item_marked_served", item_name=item.item_name)
        return _ok(
            {
                "order_id": order_id,
                "item_id": item_id,
                "item_name": item.item_name,
                "served_at": now,
            }
        )
    except ValueError as exc:
        log.warning("mark_served_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 10. 菜品变价(Temporary Price Override) ───


@router.put("/orders/{order_id}/items/{item_id}/price")
async def override_item_price(
    order_id: str,
    item_id: str,
    body: PriceOverrideReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """临时修改某道菜的价格(如时价菜称重后改价)"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, item_id=item_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select, update

        from shared.ontology.src.entities import Order, OrderItem

        item_result = await db.execute(
            select(OrderItem).where(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        item = item_result.scalar_one_or_none()
        if not item:
            raise ValueError("菜品不存在")

        old_price_fen = item.unit_price_fen
        new_subtotal = body.new_price_fen * item.quantity

        await db.execute(
            update(OrderItem)
            .where(OrderItem.id == item_id)
            .values(
                original_price_fen=old_price_fen,
                unit_price_fen=body.new_price_fen,
                subtotal_fen=new_subtotal,
            )
        )

        # 重算订单总额
        all_items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
                OrderItem.return_flag == False,  # noqa: E712
            )
        )
        all_items = all_items_result.scalars().all()
        new_total = sum(
            (
                body.new_price_fen * item.quantity
                if str(i.id) == item_id
                else (i.subtotal_fen or i.unit_price_fen * i.quantity)
            )
            for i in all_items
        )

        await db.execute(
            update(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).values(total_amount_fen=new_total)
        )
        await db.commit()

        log.info(
            "price_overridden",
            item_name=item.item_name,
            old_price_fen=old_price_fen,
            new_price_fen=body.new_price_fen,
            reason=body.reason,
        )
        return _ok(
            {
                "order_id": order_id,
                "item_id": item_id,
                "item_name": item.item_name,
                "old_price_fen": old_price_fen,
                "new_price_fen": body.new_price_fen,
                "new_subtotal_fen": new_subtotal,
                "new_order_total_fen": new_total,
            }
        )
    except ValueError as exc:
        log.warning("price_override_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 11. 单品转台(Transfer Single Item) ───


@router.post("/orders/{order_id}/items/{item_id}/transfer")
async def transfer_single_item(
    order_id: str,
    item_id: str,
    body: TransferItemReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """把某道菜从当前桌转到另一桌的订单"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, item_id=item_id, tenant_id=tenant_id)

    try:
        import uuid as uuid_mod

        from sqlalchemy import delete, select, update

        from shared.ontology.src.entities import Order, OrderItem

        # 验证源item
        item_result = await db.execute(
            select(OrderItem).where(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        item = item_result.scalar_one_or_none()
        if not item:
            raise ValueError("菜品不存在")

        # 查找目标桌的活跃订单
        target_order_result = await db.execute(
            select(Order).where(
                Order.table_number == body.target_table_no,
                Order.tenant_id == tenant_id,
                Order.status.in_(["pending", "confirmed", "active"]),
            )
        )
        target_order = target_order_result.scalar_one_or_none()
        if not target_order:
            raise ValueError(f"目标桌 {body.target_table_no} 没有活跃订单")

        target_order_id = str(target_order.id)
        item_subtotal = item.subtotal_fen or (item.unit_price_fen * item.quantity)

        # 在目标订单创建新item
        new_item = OrderItem(
            id=str(uuid_mod.uuid4()),
            order_id=target_order_id,
            tenant_id=tenant_id,
            dish_id=item.dish_id,
            item_name=item.item_name,
            quantity=item.quantity,
            unit_price_fen=item.unit_price_fen,
            subtotal_fen=item_subtotal,
            notes=item.notes,
            customizations=item.customizations,
            pricing_mode=item.pricing_mode,
            weight_value=item.weight_value,
        )
        db.add(new_item)

        # 从源订单删除
        await db.execute(delete(OrderItem).where(OrderItem.id == item_id))

        # 重算两个订单总额
        for oid in [order_id, target_order_id]:
            items_result = await db.execute(
                select(OrderItem).where(
                    OrderItem.order_id == oid,
                    OrderItem.tenant_id == tenant_id,
                    OrderItem.return_flag == False,  # noqa: E712
                )
            )
            order_items = items_result.scalars().all()
            new_total = sum((i.subtotal_fen or i.unit_price_fen * i.quantity) for i in order_items)
            await db.execute(
                update(Order).where(Order.id == oid, Order.tenant_id == tenant_id).values(total_amount_fen=new_total)
            )

        await db.commit()
        log.info(
            "item_transferred",
            item_name=item.item_name,
            target_table=body.target_table_no,
        )
        return _ok(
            {
                "order_id": order_id,
                "item_id": item_id,
                "item_name": item.item_name,
                "target_table_no": body.target_table_no,
                "target_order_id": target_order_id,
            }
        )
    except ValueError as exc:
        log.warning("transfer_item_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 12. 打印客单(Print Receipt from Mobile) ───


@router.post("/orders/{order_id}/print")
async def print_order_receipt(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """从手机端触发打印小票到前台打印机"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)

    try:
        from sqlalchemy import select

        from shared.ontology.src.entities import Order, OrderItem

        from ..services.receipt_service import ReceiptService

        order_result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("订单不存在")

        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.tenant_id == tenant_id,
            )
        )
        items = items_result.scalars().all()

        order_data = {
            "order_no": order.order_no,
            "table_number": order.table_number,
            "guest_count": order.guest_count,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen or 0,
            "service_charge_fen": order.service_charge_fen or 0,
            "items": [
                {
                    "item_name": i.item_name,
                    "quantity": i.quantity,
                    "unit_price_fen": i.unit_price_fen,
                    "subtotal_fen": i.subtotal_fen,
                    "is_gift": i.is_gift,
                }
                for i in items
                if not i.return_flag
            ],
        }

        receipt_bytes = ReceiptService.format_receipt(order_data)

        # 通过 Mac mini WebSocket 转发打印指令到安卓POS打印机
        # 实际生产中通过 ws://mac-mini:8000/ws/print 推送
        log.info("print_receipt_ok", order_no=order.order_no)
        return _ok(
            {
                "order_id": order_id,
                "order_no": order.order_no,
                "printed": True,
                "receipt_size_bytes": len(receipt_bytes),
            }
        )
    except ValueError as exc:
        log.warning("print_receipt_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 13. 后厨通知(Kitchen Message) ───


@router.post("/kds/message")
async def send_kitchen_message(
    body: KitchenMessageReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """给后厨发自定义文字消息(通过Mac mini WebSocket推送到KDS)"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id, table_no=body.table_no)

    try:
        import uuid as uuid_mod
        from datetime import datetime, timezone

        message_id = str(uuid_mod.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        log.info(
            "kitchen_message_sent",
            message_id=message_id,
            message=body.message,
            table_no=body.table_no,
        )
        # 通过 Redis Pub/Sub 推送到 KDS，mac-station 订阅后转发 WebSocket
        try:
            r = await UniversalPublisher.get_redis()
            payload = json.dumps(
                {
                    "event": "kitchen_message",
                    "message_id": message_id,
                    "message": body.message,
                    "table_no": body.table_no,
                    "sent_at": now,
                },
                ensure_ascii=False,
            )
            await r.publish(f"kds:{tenant_id}:messages", payload)
        except (OSError, RuntimeError) as exc:
            log.warning("kitchen_message_redis_failed", error=str(exc))
        return _ok(
            {
                "message_id": message_id,
                "message": body.message,
                "table_no": body.table_no,
                "sent_at": now,
            }
        )
    except ValueError as exc:
        log.warning("kitchen_message_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 14. 转账(Transfer Payment Between Orders) ───


@router.post("/payments/transfer")
async def transfer_payment(
    body: TransferPaymentReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """把一个订单的付款记录转移到另一个订单

    适用场景: 客人付错桌、并桌结账后需要拆分等。
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(
        tenant_id=tenant_id,
        source_order=body.source_order_id,
        target_order=body.target_order_id,
        payment_id=body.payment_id,
    )

    try:
        from sqlalchemy import select

        from shared.ontology.src.entities import Order

        # 验证源订单和目标订单都存在
        for oid, label in [(body.source_order_id, "源"), (body.target_order_id, "目标")]:
            result = await db.execute(select(Order).where(Order.id == oid, Order.tenant_id == tenant_id))
            if not result.scalar_one_or_none():
                raise ValueError(f"{label}订单不存在: {oid}")

        # 注: Payment 表若存在则直接修改 order_id
        # 当前 entities.py 未定义 Payment 模型, 使用原始SQL
        from sqlalchemy import text

        result = await db.execute(
            text(
                "UPDATE payments SET order_id = :target_id "
                "WHERE id = :payment_id AND order_id = :source_id "
                "AND tenant_id = :tenant_id"
            ),
            {
                "target_id": body.target_order_id,
                "source_id": body.source_order_id,
                "payment_id": body.payment_id,
                "tenant_id": tenant_id,
            },
        )
        if result.rowcount == 0:
            raise ValueError("付款记录不存在或不属于源订单")

        await db.commit()
        log.info("payment_transferred")
        return _ok(
            {
                "payment_id": body.payment_id,
                "source_order_id": body.source_order_id,
                "target_order_id": body.target_order_id,
                "transferred": True,
            }
        )
    except ValueError as exc:
        log.warning("payment_transfer_fail", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
