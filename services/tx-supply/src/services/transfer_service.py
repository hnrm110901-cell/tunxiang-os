"""门店间库存调拨服务

调拨流程：
  创建申请（draft）→ 审批通过（approved）→ 发货（shipped，from_store 扣库存）
  → 收货（received，to_store 加库存）

库存操作：
  发货：transaction_type='transfer_out'，from_store 扣减
  收货：transaction_type='transfer_in'，to_store 增加
  运输损耗：shipped - received 部分记入 waste
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.events import SupplyEventType, UniversalPublisher
from shared.ontology.src.entities import (
    Ingredient,
    IngredientTransaction,
    TransferOrder,
    TransferOrderItem,
)
from shared.ontology.src.enums import (
    InventoryStatus,
    TransactionType,
    TransferOrderStatus,
)

logger = structlog.get_logger(__name__)


# ─── 内部工具 ─────────────────────────────────────────────


class InsufficientStockError(ValueError):
    """库存不足错误"""


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    from sqlalchemy import text

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _update_ingredient_status(ingredient: Ingredient) -> str:
    qty = ingredient.current_quantity
    min_qty = ingredient.min_quantity
    if qty <= 0:
        status = InventoryStatus.out_of_stock.value
    elif qty <= min_qty * 0.5:
        status = InventoryStatus.critical.value
    elif qty <= min_qty:
        status = InventoryStatus.low.value
    else:
        status = InventoryStatus.normal.value
    ingredient.status = status
    return status


async def _get_ingredient(
    db: AsyncSession,
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
) -> Ingredient:
    result = await db.execute(
        select(Ingredient).where(
            Ingredient.id == _uuid(ingredient_id),
            Ingredient.store_id == _uuid(store_id),
            Ingredient.tenant_id == _uuid(tenant_id),
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ing = result.scalar_one_or_none()
    if ing is None:
        raise ValueError(f"原料 {ingredient_id} 在门店 {store_id} 不存在")
    return ing


def _order_to_dict(o: TransferOrder) -> dict:
    return {
        "order_id": str(o.id),
        "from_store_id": str(o.from_store_id),
        "to_store_id": str(o.to_store_id),
        "status": o.status,
        "transfer_reason": o.transfer_reason,
        "requested_by": str(o.requested_by) if o.requested_by else None,
        "approved_by": str(o.approved_by) if o.approved_by else None,
        "requested_at": o.requested_at.isoformat() if o.requested_at else None,
        "approved_at": o.approved_at.isoformat() if o.approved_at else None,
        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
        "received_at": o.received_at.isoformat() if o.received_at else None,
        "notes": o.notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _item_to_dict(i: TransferOrderItem) -> dict:
    return {
        "item_id": str(i.id),
        "transfer_order_id": str(i.transfer_order_id),
        "ingredient_id": str(i.ingredient_id),
        "ingredient_name": i.ingredient_name,
        "requested_quantity": float(i.requested_quantity or 0),
        "unit": i.unit,
        "approved_quantity": float(i.approved_quantity) if i.approved_quantity is not None else None,
        "shipped_quantity": float(i.shipped_quantity) if i.shipped_quantity is not None else None,
        "received_quantity": float(i.received_quantity) if i.received_quantity is not None else None,
        "batch_no": i.batch_no,
        "unit_cost_fen": i.unit_cost_fen,
    }


# ─── 1. 创建调拨申请 ─────────────────────────────────────


async def create_transfer_order(
    tenant_id: str,
    from_store_id: str,
    to_store_id: str,
    items: list[dict],
    db: AsyncSession,
    transfer_reason: Optional[str] = None,
    requested_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """创建调拨申请（status='draft'）。

    items 每项包含：ingredient_id, ingredient_name, requested_quantity, unit
    """
    if from_store_id == to_store_id:
        raise ValueError("调出门店和调入门店不能是同一门店")
    if not items:
        raise ValueError("调拨单至少包含一项")

    await _set_tenant(db, tenant_id)

    now = _now()
    order = TransferOrder(
        id=uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        from_store_id=_uuid(from_store_id),
        to_store_id=_uuid(to_store_id),
        status=TransferOrderStatus.draft.value,
        transfer_reason=transfer_reason,
        requested_by=_uuid(requested_by) if requested_by else None,
        requested_at=now,
        notes=notes,
    )
    db.add(order)
    await db.flush()

    for item_data in items:
        item = TransferOrderItem(
            id=uuid.uuid4(),
            tenant_id=_uuid(tenant_id),
            transfer_order_id=order.id,
            ingredient_id=_uuid(item_data["ingredient_id"]),
            ingredient_name=item_data["ingredient_name"],
            requested_quantity=Decimal(str(item_data["requested_quantity"])),
            unit=item_data.get("unit", ""),
        )
        db.add(item)

    await db.flush()

    logger.info(
        "transfer_order_created",
        order_id=str(order.id),
        from_store_id=from_store_id,
        to_store_id=to_store_id,
        tenant_id=tenant_id,
        item_count=len(items),
    )

    return {
        "order_id": str(order.id),
        "status": order.status,
        "from_store_id": from_store_id,
        "to_store_id": to_store_id,
        "item_count": len(items),
        "created_at": now.isoformat(),
    }


# ─── 2. 列表 / 详情 查询 ─────────────────────────────────


async def list_transfer_orders(
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """查询调拨单列表。

    role='from' → 仅调出方；role='to' → 仅调入方；None → 两者均包含。
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)

    filters = [
        TransferOrder.tenant_id == tid,
        TransferOrder.is_deleted == False,  # noqa: E712
    ]
    if store_id:
        sid = _uuid(store_id)
        if role == "from":
            filters.append(TransferOrder.from_store_id == sid)
        elif role == "to":
            filters.append(TransferOrder.to_store_id == sid)
        else:
            filters.append((TransferOrder.from_store_id == sid) | (TransferOrder.to_store_id == sid))
    if status:
        filters.append(TransferOrder.status == status)

    count_q = select(func.count(TransferOrder.id)).where(*filters)
    total = (await db.execute(count_q)).scalar() or 0

    items_q = (
        select(TransferOrder)
        .where(*filters)
        .order_by(TransferOrder.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await db.execute(items_q)).scalars().all()

    return {
        "items": [_order_to_dict(o) for o in rows],
        "total": total,
        "page": page,
        "size": size,
    }


async def get_transfer_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取调拨单详情（含明细）"""
    await _set_tenant(db, tenant_id)
    q = (
        select(TransferOrder)
        .options(selectinload(TransferOrder.items))
        .where(
            TransferOrder.id == _uuid(order_id),
            TransferOrder.tenant_id == _uuid(tenant_id),
            TransferOrder.is_deleted == False,  # noqa: E712
        )
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        raise ValueError(f"调拨单 {order_id} 不存在")

    result = _order_to_dict(row)
    result["items"] = [_item_to_dict(i) for i in row.items]
    return result


# ─── 3. 审批 ─────────────────────────────────────────────


async def approve_transfer_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    approved_by: str,
    approved_items: list[dict],  # [{item_id, approved_quantity}]
) -> dict:
    """审批调拨单。

    检查 from_store 库存是否足够，更新审批数量。
    approved_items 为空时，全部按申请数量审批。
    """
    await _set_tenant(db, tenant_id)

    q = (
        select(TransferOrder)
        .options(selectinload(TransferOrder.items))
        .where(
            TransferOrder.id == _uuid(order_id),
            TransferOrder.tenant_id == _uuid(tenant_id),
            TransferOrder.is_deleted == False,  # noqa: E712
        )
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"调拨单 {order_id} 不存在")
    if order.status != TransferOrderStatus.draft.value:
        raise ValueError(f"调拨单状态为 {order.status}，不能审批")

    # 构建审批数量 map
    approved_map = {i["item_id"]: Decimal(str(i["approved_quantity"])) for i in approved_items}

    # 检查 from_store 库存
    await _check_transfer_feasibility(
        from_store_id=str(order.from_store_id),
        tenant_id=tenant_id,
        items=order.items,
        approved_map=approved_map,
        db=db,
    )

    now = _now()
    for item in order.items:
        item_id_str = str(item.id)
        if item_id_str in approved_map:
            item.approved_quantity = approved_map[item_id_str]
        else:
            item.approved_quantity = item.requested_quantity

    order.status = TransferOrderStatus.approved.value
    order.approved_by = _uuid(approved_by)
    order.approved_at = now
    await db.flush()

    logger.info(
        "transfer_order_approved",
        order_id=order_id,
        approved_by=approved_by,
        tenant_id=tenant_id,
    )

    result = _order_to_dict(order)
    result["items"] = [_item_to_dict(i) for i in order.items]
    return result


async def _check_transfer_feasibility(
    from_store_id: str,
    tenant_id: str,
    items: list[TransferOrderItem],
    approved_map: dict[str, Decimal],
    db: AsyncSession,
) -> None:
    """检查 from_store 对每个食材的库存是否足够。"""
    sid = _uuid(from_store_id)
    tid = _uuid(tenant_id)

    for item in items:
        qty_needed = approved_map.get(str(item.id), item.requested_quantity)
        if qty_needed <= Decimal("0"):
            continue

        result = await db.execute(
            select(Ingredient).where(
                Ingredient.id == item.ingredient_id,
                Ingredient.store_id == sid,
                Ingredient.tenant_id == tid,
                Ingredient.is_deleted == False,  # noqa: E712
            )
        )
        ing = result.scalar_one_or_none()
        if ing is None:
            raise InsufficientStockError(f"调出门店没有食材 {item.ingredient_name}（id={item.ingredient_id}）")
        if ing.current_quantity < float(qty_needed):
            raise InsufficientStockError(
                f"{item.ingredient_name} 调出门店库存不足：现有 {ing.current_quantity}{ing.unit}，需要 {qty_needed}"
            )


# ─── 4. 发货（from_store 扣库存） ────────────────────────


async def ship_transfer_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    shipped_items: list[dict],  # [{item_id, shipped_quantity, batch_no}]
    operator_id: Optional[str] = None,
) -> dict:
    """标记已发货，从 from_store 扣减库存。"""
    await _set_tenant(db, tenant_id)

    q = (
        select(TransferOrder)
        .options(selectinload(TransferOrder.items))
        .where(
            TransferOrder.id == _uuid(order_id),
            TransferOrder.tenant_id == _uuid(tenant_id),
            TransferOrder.is_deleted == False,  # noqa: E712
        )
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"调拨单 {order_id} 不存在")
    if order.status != TransferOrderStatus.approved.value:
        raise ValueError(f"调拨单状态为 {order.status}，必须先审批才能发货")

    shipped_map = {
        i["item_id"]: {
            "quantity": Decimal(str(i["shipped_quantity"])),
            "batch_no": i.get("batch_no"),
        }
        for i in shipped_items
    }

    now = _now()
    inventory_results = []

    for item in order.items:
        item_id_str = str(item.id)
        if item_id_str not in shipped_map:
            # 未填写的按审批数量发货
            ship_qty = item.approved_quantity or item.requested_quantity
            batch_no = item.batch_no
        else:
            ship_qty = shipped_map[item_id_str]["quantity"]
            batch_no = shipped_map[item_id_str]["batch_no"]

        if ship_qty <= Decimal("0"):
            continue

        item.shipped_quantity = ship_qty
        if batch_no:
            item.batch_no = batch_no

        # 扣减 from_store 库存
        ing = await _get_ingredient(db, str(item.ingredient_id), str(order.from_store_id), tenant_id)
        if ing.current_quantity < float(ship_qty):
            raise InsufficientStockError(
                f"{item.ingredient_name} 库存不足: 现有 {ing.current_quantity}{ing.unit}，发货需要 {ship_qty}"
            )

        qty_before = ing.current_quantity
        qty_after = qty_before - float(ship_qty)
        ing.current_quantity = qty_after
        item.unit_cost_fen = ing.unit_price_fen
        _update_ingredient_status(ing)

        tx = IngredientTransaction(
            id=uuid.uuid4(),
            tenant_id=_uuid(tenant_id),
            ingredient_id=item.ingredient_id,
            store_id=order.from_store_id,
            transaction_type=TransactionType.transfer_out.value,
            quantity=float(ship_qty),
            unit_cost_fen=ing.unit_price_fen,
            total_cost_fen=round((ing.unit_price_fen or 0) * float(ship_qty)),
            quantity_before=qty_before,
            quantity_after=qty_after,
            performed_by=operator_id,
            reference_id=str(order.id),
            notes=f"调拨至门店 {order.to_store_id}",
        )
        db.add(tx)
        inventory_results.append(
            {
                "ingredient_id": str(item.ingredient_id),
                "ingredient_name": item.ingredient_name,
                "shipped_quantity": float(ship_qty),
                "qty_before": qty_before,
                "qty_after": qty_after,
                "transaction_id": str(tx.id),
            }
        )

    order.status = TransferOrderStatus.shipped.value
    order.shipped_at = now
    await db.flush()

    logger.info(
        "transfer_order_shipped",
        order_id=order_id,
        from_store_id=str(order.from_store_id),
        tenant_id=tenant_id,
        item_count=len(inventory_results),
    )

    return {
        "order_id": order_id,
        "status": order.status,
        "shipped_at": now.isoformat(),
        "inventory_results": inventory_results,
    }


# ─── 5. 收货（to_store 加库存） ──────────────────────────


async def receive_transfer_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    received_items: list[dict],  # [{item_id, received_quantity}]
    operator_id: Optional[str] = None,
) -> dict:
    """标记已收货，向 to_store 增加库存。

    若 received_quantity < shipped_quantity，差值记为运输损耗（transaction_type='waste'）。
    """
    await _set_tenant(db, tenant_id)

    q = (
        select(TransferOrder)
        .options(selectinload(TransferOrder.items))
        .where(
            TransferOrder.id == _uuid(order_id),
            TransferOrder.tenant_id == _uuid(tenant_id),
            TransferOrder.is_deleted == False,  # noqa: E712
        )
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"调拨单 {order_id} 不存在")
    if order.status != TransferOrderStatus.shipped.value:
        raise ValueError(f"调拨单状态为 {order.status}，必须先发货才能确认收货")

    received_map = {i["item_id"]: Decimal(str(i["received_quantity"])) for i in received_items}

    now = _now()
    inventory_results = []
    loss_results = []

    for item in order.items:
        item_id_str = str(item.id)
        shipped_qty = float(item.shipped_quantity or 0)
        if item_id_str not in received_map:
            recv_qty_dec = item.shipped_quantity or Decimal("0")
        else:
            recv_qty_dec = received_map[item_id_str]

        recv_qty = float(recv_qty_dec)
        if recv_qty < 0:
            raise ValueError(f"收货数量不能为负：{item.ingredient_name}")
        if recv_qty > shipped_qty:
            raise ValueError(f"{item.ingredient_name} 收货数量({recv_qty}) 超过发货数量({shipped_qty})")

        item.received_quantity = recv_qty_dec

        if recv_qty > 0:
            # 增加 to_store 库存
            # ingredient_id 是 from_store 的台账行，to_store 用 ingredient_name 查找对应行
            ing_result = await db.execute(
                select(Ingredient).where(
                    Ingredient.ingredient_name == item.ingredient_name,
                    Ingredient.store_id == order.to_store_id,
                    Ingredient.tenant_id == _uuid(tenant_id),
                    Ingredient.is_deleted == False,  # noqa: E712
                )
            )
            to_ing = ing_result.scalar_one_or_none()
            if to_ing is None:
                raise ValueError(f"调入门店没有食材 {item.ingredient_name}，请先建立门店食材台账")

            qty_before = to_ing.current_quantity
            qty_after = qty_before + recv_qty
            cost = item.unit_cost_fen

            if cost is not None:
                if to_ing.unit_price_fen and qty_before > 0:
                    total_c = to_ing.unit_price_fen * qty_before + cost * recv_qty
                    to_ing.unit_price_fen = round(total_c / qty_after)
                else:
                    to_ing.unit_price_fen = cost

            to_ing.current_quantity = qty_after
            _update_ingredient_status(to_ing)

            tx_in = IngredientTransaction(
                id=uuid.uuid4(),
                tenant_id=_uuid(tenant_id),
                ingredient_id=to_ing.id,  # to_store 的台账行 id
                store_id=order.to_store_id,
                transaction_type=TransactionType.transfer_in.value,
                quantity=recv_qty,
                unit_cost_fen=cost,
                total_cost_fen=round((cost or 0) * recv_qty),
                quantity_before=qty_before,
                quantity_after=qty_after,
                performed_by=operator_id,
                reference_id=str(order.id),
                notes=f"来自门店 {order.from_store_id} 调拨",
            )
            db.add(tx_in)
            inventory_results.append(
                {
                    "ingredient_id": str(to_ing.id),
                    "ingredient_name": item.ingredient_name,
                    "received_quantity": recv_qty,
                    "qty_before": qty_before,
                    "qty_after": qty_after,
                    "transaction_id": str(tx_in.id),
                }
            )

        # 运输损耗
        loss = shipped_qty - recv_qty
        if loss > 0.001:
            loss_results.append(
                {
                    "ingredient_id": str(item.ingredient_id),
                    "ingredient_name": item.ingredient_name,
                    "shipped": shipped_qty,
                    "received": recv_qty,
                    "loss": loss,
                }
            )
            logger.warning(
                "transfer_transit_loss",
                order_id=order_id,
                ingredient_id=str(item.ingredient_id),
                shipped=shipped_qty,
                received=recv_qty,
                loss=loss,
            )

    order.status = TransferOrderStatus.received.value
    order.received_at = now
    await db.flush()

    logger.info(
        "transfer_order_received",
        order_id=order_id,
        to_store_id=str(order.to_store_id),
        tenant_id=tenant_id,
        received_count=len(inventory_results),
        loss_count=len(loss_results),
    )

    # ── 事件总线：门店调拨完成 ──────────────────────────────
    asyncio.create_task(
        UniversalPublisher.publish(
            event_type=SupplyEventType.TRANSFER_COMPLETED,
            tenant_id=_uuid(tenant_id),
            store_id=order.to_store_id,
            entity_id=order.id,
            event_data={
                "from_store_id": str(order.from_store_id),
                "to_store_id": str(order.to_store_id),
                "items_count": len(inventory_results),
            },
            source_service="tx-supply",
        )
    )

    return {
        "order_id": order_id,
        "status": order.status,
        "received_at": now.isoformat(),
        "inventory_results": inventory_results,
        "transit_losses": loss_results,
    }


# ─── 6. 取消调拨 ─────────────────────────────────────────


async def cancel_transfer_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    cancelled_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """取消调拨单（仅 draft/approved 状态可取消）。"""
    await _set_tenant(db, tenant_id)

    q = select(TransferOrder).where(
        TransferOrder.id == _uuid(order_id),
        TransferOrder.tenant_id == _uuid(tenant_id),
        TransferOrder.is_deleted == False,  # noqa: E712
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"调拨单 {order_id} 不存在")
    if order.status not in (TransferOrderStatus.draft.value, TransferOrderStatus.approved.value):
        raise ValueError(f"调拨单状态为 {order.status}，已发货/收货的单据不能取消")

    order.status = TransferOrderStatus.cancelled.value
    if reason:
        order.notes = (order.notes or "") + f"\n取消原因: {reason}"
    await db.flush()

    logger.info(
        "transfer_order_cancelled",
        order_id=order_id,
        cancelled_by=cancelled_by,
        tenant_id=tenant_id,
    )

    return {"order_id": order_id, "status": order.status}


# ─── 7. 库存查询（辅助调拨决策） ─────────────────────────


async def get_store_ingredient_stock(
    store_id: str,
    ingredient_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询指定门店某食材的当前库存。"""
    await _set_tenant(db, tenant_id)
    ing = await _get_ingredient(db, ingredient_id, store_id, tenant_id)
    return {
        "store_id": store_id,
        "ingredient_id": ingredient_id,
        "ingredient_name": ing.ingredient_name,
        "quantity": ing.current_quantity,
        "unit": ing.unit,
        "unit_price_fen": ing.unit_price_fen,
        "status": ing.status,
        "min_quantity": ing.min_quantity,
    }


async def get_brand_ingredient_overview(
    tenant_id: str,
    ingredient_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询租户下所有门店某食材的库存量（品牌维度）。

    便于决策从哪个门店调拨。
    Returns: [{store_id, store_name, quantity, unit, days_of_stock}]
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)
    iid = _uuid(ingredient_id)

    result = await db.execute(
        select(Ingredient).where(
            Ingredient.tenant_id == tid,
            Ingredient.id == iid,
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    # ingredient_id 是门店台账 id，需用 ingredient_name 关联
    # 实际上每个门店的同一食材有独立的 Ingredient 行，通过 ingredient_name 聚合
    # 这里按 ingredient_id 只查一行；调用方应传 ingredient_name 横向对比
    # 为正确实现品牌概览，直接查询同名食材在所有门店的库存
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"食材 {ingredient_id} 不存在")

    # 查同 tenant 下同名食材的所有门店库存
    name_result = await db.execute(
        select(Ingredient).where(
            Ingredient.tenant_id == tid,
            Ingredient.ingredient_name == row.ingredient_name,
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    all_rows = name_result.scalars().all()

    overview = []
    for ing in all_rows:
        days_of_stock = None
        overview.append(
            {
                "store_id": str(ing.store_id),
                "ingredient_id": str(ing.id),
                "ingredient_name": ing.ingredient_name,
                "quantity": ing.current_quantity,
                "unit": ing.unit,
                "min_quantity": ing.min_quantity,
                "status": ing.status,
                "unit_price_fen": ing.unit_price_fen,
                "days_of_stock": days_of_stock,
            }
        )

    # 按库存量降序
    overview.sort(key=lambda x: x["quantity"], reverse=True)
    return overview


async def get_brand_low_stock_alert(
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """全品牌低库存预警：所有门店中库存低于安全库存的食材。"""
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)

    result = await db.execute(
        select(Ingredient)
        .where(
            Ingredient.tenant_id == tid,
            Ingredient.is_deleted == False,  # noqa: E712
            Ingredient.status.in_(
                [
                    InventoryStatus.low.value,
                    InventoryStatus.critical.value,
                    InventoryStatus.out_of_stock.value,
                ]
            ),
        )
        .order_by(Ingredient.status, Ingredient.ingredient_name)
    )
    rows = result.scalars().all()

    alerts = []
    for ing in rows:
        alerts.append(
            {
                "store_id": str(ing.store_id),
                "ingredient_id": str(ing.id),
                "ingredient_name": ing.ingredient_name,
                "category": ing.category,
                "quantity": ing.current_quantity,
                "min_quantity": ing.min_quantity,
                "unit": ing.unit,
                "status": ing.status,
                "unit_price_fen": ing.unit_price_fen,
            }
        )

    return alerts
