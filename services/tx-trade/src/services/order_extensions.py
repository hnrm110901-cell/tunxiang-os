"""点单扩展服务 — 赠菜/拆单/并单/异常改单

赠菜必须有审批人，所有金额单位：分（fen）。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from shared.ontology.src.enums import OrderStatus

logger = structlog.get_logger()


# ─── 内部数据模型 ───


class _OrderChangeRequest:
    """改单申请（轻量模型，不依赖额外表）"""

    _store: dict[str, dict] = {}  # change_id -> change_data

    @classmethod
    def save(cls, change_id: str, data: dict) -> None:
        cls._store[change_id] = data

    @classmethod
    def get(cls, change_id: str) -> Optional[dict]:
        return cls._store.get(change_id)


# ─── 赠菜 ───


async def gift_dish(
    order_id: str,
    dish_id: str,
    quantity: int,
    reason: str,
    approver_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """赠菜 — 需审批人签字

    硬约束：approver_id 不可为空，赠菜将菜品标记 gift_flag=True、单价归零。
    """
    if not approver_id:
        raise ValueError("赠菜必须有审批人(approver_id)")

    if quantity <= 0:
        raise ValueError("赠菜数量必须大于0")

    # 查询订单
    result = await db.execute(
        select(Order).where(
            Order.id == uuid.UUID(order_id),
            Order.tenant_id == uuid.UUID(tenant_id),
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"Order not found: {order_id}")

    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise ValueError(f"订单状态({order.status})不允许赠菜")

    # 创建赠菜明细项（单价0、gift_flag=True）
    item = OrderItem(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        order_id=uuid.UUID(order_id),
        dish_id=uuid.UUID(dish_id),
        item_name=f"[赠]{dish_id[:8]}",
        quantity=quantity,
        unit_price_fen=0,
        subtotal_fen=0,
        gift_flag=True,
        notes=f"赠菜原因: {reason} | 审批人: {approver_id}",
    )
    db.add(item)
    await db.flush()

    logger.info(
        "gift_dish_added",
        order_id=order_id,
        dish_id=dish_id,
        quantity=quantity,
        approver_id=approver_id,
        tenant_id=tenant_id,
    )
    return {
        "item_id": str(item.id),
        "order_id": order_id,
        "dish_id": dish_id,
        "quantity": quantity,
        "gift_flag": True,
        "approver_id": approver_id,
        "reason": reason,
    }


# ─── 拆单 ───


async def split_order(
    order_id: str,
    items_groups: list[list[str]],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """拆单 — 一桌拆成多单

    items_groups: [[item_id, ...], [item_id, ...]]，每组生成一个新订单。
    原订单保留第一组，剩余组创建新订单。
    """
    if len(items_groups) < 2:
        raise ValueError("拆单至少需要两组")

    # 加载原订单
    result = await db.execute(
        select(Order).where(
            Order.id == uuid.UUID(order_id),
            Order.tenant_id == uuid.UUID(tenant_id),
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"Order not found: {order_id}")

    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise ValueError(f"订单状态({order.status})不允许拆单")

    # 加载所有明细
    items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == uuid.UUID(order_id)))
    all_items = {str(i.id): i for i in items_result.scalars().all()}

    # 校验所有 item_id 存在
    for group in items_groups:
        for iid in group:
            if iid not in all_items:
                raise ValueError(f"OrderItem not found: {iid}")

    new_order_ids: list[str] = []

    # 第一组保留在原订单
    first_group_ids = set(items_groups[0])
    first_group_total = sum(all_items[iid].subtotal_fen for iid in first_group_ids if iid in all_items)

    # 从第二组开始，为每组创建新订单
    for group_idx, group in enumerate(items_groups[1:], start=2):
        group_total = sum(all_items[iid].subtotal_fen for iid in group if iid in all_items)
        now = datetime.now(timezone.utc)
        new_order_id = uuid.uuid4()
        new_order = Order(
            id=new_order_id,
            tenant_id=uuid.UUID(tenant_id),
            order_no=f"{order.order_no}-S{group_idx}",
            store_id=order.store_id,
            table_number=order.table_number,
            customer_id=order.customer_id,
            waiter_id=order.waiter_id,
            sales_channel_id=order.sales_channel_id,
            total_amount_fen=group_total,
            discount_amount_fen=0,
            final_amount_fen=group_total,
            status=order.status,
        )
        db.add(new_order)

        # 将明细项移到新订单
        for iid in group:
            item = all_items[iid]
            item.order_id = new_order_id

        new_order_ids.append(str(new_order_id))

    # 更新原订单总额（只保留第一组）
    order.total_amount_fen = first_group_total
    order.final_amount_fen = first_group_total - order.discount_amount_fen

    await db.flush()

    logger.info(
        "order_split",
        original_order_id=order_id,
        new_order_ids=new_order_ids,
        group_count=len(items_groups),
        tenant_id=tenant_id,
    )
    return {
        "original_order_id": order_id,
        "new_order_ids": new_order_ids,
        "group_count": len(items_groups),
    }


# ─── 并单 ───


async def merge_orders(
    order_ids: list[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """并单 — 多单合并为一单

    以第一个 order_id 为主单，其余订单的明细移入主单，副单标记取消。
    """
    if len(order_ids) < 2:
        raise ValueError("并单至少需要两个订单")

    primary_id = order_ids[0]
    secondary_ids = order_ids[1:]

    # 加载主单
    result = await db.execute(
        select(Order).where(
            Order.id == uuid.UUID(primary_id),
            Order.tenant_id == uuid.UUID(tenant_id),
        )
    )
    primary_order = result.scalar_one_or_none()
    if not primary_order:
        raise ValueError(f"主单不存在: {primary_id}")

    merged_amount = primary_order.total_amount_fen

    for sid in secondary_ids:
        result = await db.execute(
            select(Order).where(
                Order.id == uuid.UUID(sid),
                Order.tenant_id == uuid.UUID(tenant_id),
            )
        )
        sec_order = result.scalar_one_or_none()
        if not sec_order:
            raise ValueError(f"副单不存在: {sid}")

        if sec_order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
            raise ValueError(f"订单 {sid} 状态({sec_order.status})不允许并单")

        # 移动副单明细到主单
        await db.execute(
            update(OrderItem).where(OrderItem.order_id == uuid.UUID(sid)).values(order_id=uuid.UUID(primary_id))
        )

        merged_amount += sec_order.total_amount_fen

        # 副单标记取消
        sec_order.status = OrderStatus.cancelled.value
        sec_order.order_metadata = {
            **(sec_order.order_metadata or {}),
            "merged_into": primary_id,
        }

    # 更新主单总额
    primary_order.total_amount_fen = merged_amount
    primary_order.final_amount_fen = merged_amount - primary_order.discount_amount_fen

    await db.flush()

    logger.info(
        "orders_merged",
        primary_order_id=primary_id,
        merged_from=secondary_ids,
        new_total_fen=merged_amount,
        tenant_id=tenant_id,
    )
    return {
        "primary_order_id": primary_id,
        "merged_from": secondary_ids,
        "new_total_fen": merged_amount,
    }


# ─── 异常改单申请 ───


async def request_order_change(
    order_id: str,
    changes: dict,
    reason: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """异常改单申请 — 需后续审批

    changes: {"items_to_remove": [...], "items_to_add": [...], "price_adjustments": [...]}
    """
    # 校验订单存在
    result = await db.execute(
        select(Order).where(
            Order.id == uuid.UUID(order_id),
            Order.tenant_id == uuid.UUID(tenant_id),
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"Order not found: {order_id}")

    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise ValueError(f"订单状态({order.status})不允许改单")

    change_id = str(uuid.uuid4())
    change_data = {
        "change_id": change_id,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "changes": changes,
        "reason": reason,
        "status": "pending_approval",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        "approver_id": None,
    }
    _OrderChangeRequest.save(change_id, change_data)

    # 标记订单异常
    order.abnormal_flag = True
    order.abnormal_type = "change_request"
    await db.flush()

    logger.info(
        "order_change_requested",
        change_id=change_id,
        order_id=order_id,
        reason=reason,
        tenant_id=tenant_id,
    )
    return change_data


# ─── 改单审批 ───


async def approve_order_change(
    change_id: str,
    approver_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """改单审批 — 审批通过后执行改单"""
    change_data = _OrderChangeRequest.get(change_id)
    if not change_data:
        raise ValueError(f"改单申请不存在: {change_id}")

    if change_data["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")

    if change_data["status"] != "pending_approval":
        raise ValueError(f"改单申请状态异常: {change_data['status']}")

    if not approver_id:
        raise ValueError("审批人不可为空")

    # 标记审批通过
    change_data["status"] = "approved"
    change_data["approver_id"] = approver_id
    change_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    _OrderChangeRequest.save(change_id, change_data)

    order_id = change_data["order_id"]
    changes = change_data["changes"]

    # 执行改单操作：移除指定菜品
    items_to_remove = changes.get("items_to_remove", [])
    total_deducted = 0
    for item_id in items_to_remove:
        result = await db.execute(
            select(OrderItem).where(
                OrderItem.id == uuid.UUID(item_id),
                OrderItem.order_id == uuid.UUID(order_id),
            )
        )
        item = result.scalar_one_or_none()
        if item:
            total_deducted += item.subtotal_fen
            await db.delete(item)

    # 执行价格调整
    price_adjustments = changes.get("price_adjustments", [])
    total_adjustment = 0
    for adj in price_adjustments:
        result = await db.execute(
            select(OrderItem).where(
                OrderItem.id == uuid.UUID(adj["item_id"]),
                OrderItem.order_id == uuid.UUID(order_id),
            )
        )
        item = result.scalar_one_or_none()
        if item:
            old_subtotal = item.subtotal_fen
            item.unit_price_fen = adj["new_price_fen"]
            item.subtotal_fen = adj["new_price_fen"] * item.quantity
            total_adjustment += item.subtotal_fen - old_subtotal

    # 更新订单总额
    if total_deducted or total_adjustment:
        diff = total_adjustment - total_deducted
        await db.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .values(
                total_amount_fen=Order.total_amount_fen + diff,
                final_amount_fen=Order.total_amount_fen + diff - Order.discount_amount_fen,
                abnormal_flag=False,
            )
        )

    await db.flush()

    logger.info(
        "order_change_approved",
        change_id=change_id,
        order_id=order_id,
        approver_id=approver_id,
        deducted_fen=total_deducted,
        adjustment_fen=total_adjustment,
        tenant_id=tenant_id,
    )
    return change_data
