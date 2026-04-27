"""收货验收流程服务 V2 — 完整数据库持久化版本

收货验收流程:
  创建收货单 → 逐项验收 → 完成验收（入库）/ 全部拒收

入库核心：验收完成后向 ingredient_transactions 写 'receiving' 类型流水，
并更新 ingredients.current_quantity 和 unit_price_fen（加权均价）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.events import SupplyEventType, UniversalPublisher
from shared.ontology.src.entities import (
    Ingredient,
    IngredientTransaction,
    ReceivingOrder,
    ReceivingOrderItem,
)
from shared.ontology.src.enums import (
    InventoryStatus,
    ReceivingItemStatus,
    ReceivingOrderStatus,
    TransactionType,
)

logger = structlog.get_logger(__name__)

# ─── 内部工具 ─────────────────────────────────────────────


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


# ─── 1. 创建收货单 ────────────────────────────────────────


async def create_receiving_order(
    tenant_id: str,
    store_id: str,
    supplier_id: Optional[str],
    delivery_note_no: Optional[str],
    receiver_id: Optional[str],
    items: list[dict],
    db: AsyncSession,
    procurement_order_id: Optional[str] = None,
) -> dict:
    """创建收货单。

    items 每项包含：
      ingredient_id, ingredient_name, expected_quantity, expected_unit
    可选：unit_price_fen（到货单价分）

    Returns 收货单基本信息 dict。
    """
    if not items:
        raise ValueError("收货单至少包含一项")

    await _set_tenant(db, tenant_id)

    order = ReceivingOrder(
        id=uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        store_id=_uuid(store_id),
        procurement_order_id=_uuid(procurement_order_id) if procurement_order_id else None,
        supplier_id=_uuid(supplier_id) if supplier_id else None,
        delivery_note_no=delivery_note_no,
        status=ReceivingOrderStatus.draft.value,
        receiver_id=_uuid(receiver_id) if receiver_id else None,
        total_items=len(items),
        received_items=0,
        rejected_items=0,
    )
    db.add(order)
    await db.flush()

    for item_data in items:
        item = ReceivingOrderItem(
            id=uuid.uuid4(),
            tenant_id=_uuid(tenant_id),
            receiving_order_id=order.id,
            ingredient_id=_uuid(item_data["ingredient_id"]),
            ingredient_name=item_data["ingredient_name"],
            expected_quantity=Decimal(str(item_data["expected_quantity"])),
            expected_unit=item_data.get("expected_unit", ""),
            actual_quantity=Decimal("0"),
            accepted_quantity=Decimal("0"),
            rejected_quantity=Decimal("0"),
            unit_price_fen=item_data.get("unit_price_fen"),
            status=ReceivingItemStatus.pending.value,
        )
        db.add(item)

    await db.flush()

    logger.info(
        "receiving_order_created",
        order_id=str(order.id),
        store_id=store_id,
        tenant_id=tenant_id,
        item_count=len(items),
    )

    return {
        "order_id": str(order.id),
        "status": order.status,
        "store_id": store_id,
        "supplier_id": supplier_id,
        "delivery_note_no": delivery_note_no,
        "total_items": order.total_items,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


# ─── 2. 列表 / 详情 查询 ─────────────────────────────────


async def list_receiving_orders(
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """查询收货单列表"""
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)

    filters = [
        ReceivingOrder.tenant_id == tid,
        ReceivingOrder.is_deleted == False,  # noqa: E712
    ]
    if store_id:
        filters.append(ReceivingOrder.store_id == _uuid(store_id))
    if status:
        filters.append(ReceivingOrder.status == status)
    if date_from:
        filters.append(
            ReceivingOrder.created_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        )
    if date_to:
        filters.append(
            ReceivingOrder.created_at < datetime(date_to.year, date_to.month, date_to.day + 1, tzinfo=timezone.utc)
        )

    count_q = select(func.count(ReceivingOrder.id)).where(*filters)
    total = (await db.execute(count_q)).scalar() or 0

    items_q = (
        select(ReceivingOrder)
        .where(*filters)
        .order_by(ReceivingOrder.created_at.desc())
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


async def get_receiving_order(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取收货单详情（含明细）"""
    await _set_tenant(db, tenant_id)
    q = (
        select(ReceivingOrder)
        .options(selectinload(ReceivingOrder.items))
        .where(
            ReceivingOrder.id == _uuid(order_id),
            ReceivingOrder.tenant_id == _uuid(tenant_id),
            ReceivingOrder.is_deleted == False,  # noqa: E712
        )
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        raise ValueError(f"收货单 {order_id} 不存在")

    result = _order_to_dict(row)
    result["items"] = [_item_to_dict(i) for i in row.items]
    return result


# ─── 3. 单项验收 ─────────────────────────────────────────


async def inspect_item(
    order_id: str,
    item_id: str,
    tenant_id: str,
    db: AsyncSession,
    actual_quantity: Decimal,
    accepted_quantity: Decimal,
    unit_price_fen: Optional[int] = None,
    batch_no: Optional[str] = None,
    production_date: Optional[date] = None,
    expiry_date: Optional[date] = None,
    rejection_reason: Optional[str] = None,
) -> dict:
    """对收货单中的单项食材进行验收。

    accepted_quantity <= actual_quantity，差值自动计算为 rejected_quantity。
    """
    if actual_quantity < Decimal("0"):
        raise ValueError("实际数量不能为负")
    if accepted_quantity < Decimal("0"):
        raise ValueError("验收数量不能为负")
    if accepted_quantity > actual_quantity:
        raise ValueError(f"验收数量({accepted_quantity})不能超过实际到货数量({actual_quantity})")

    await _set_tenant(db, tenant_id)

    # 加载收货单（验证归属）
    order_q = select(ReceivingOrder).where(
        ReceivingOrder.id == _uuid(order_id),
        ReceivingOrder.tenant_id == _uuid(tenant_id),
        ReceivingOrder.is_deleted == False,  # noqa: E712
    )
    order = (await db.execute(order_q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"收货单 {order_id} 不存在")
    if order.status in (ReceivingOrderStatus.fully_received.value, ReceivingOrderStatus.rejected.value):
        raise ValueError(f"收货单已完成，状态：{order.status}，不能再验收")

    # 加载明细行
    item_q = select(ReceivingOrderItem).where(
        ReceivingOrderItem.id == _uuid(item_id),
        ReceivingOrderItem.receiving_order_id == _uuid(order_id),
        ReceivingOrderItem.is_deleted == False,  # noqa: E712
    )
    item = (await db.execute(item_q)).scalar_one_or_none()
    if item is None:
        raise ValueError(f"收货明细 {item_id} 不存在")

    rejected_qty = actual_quantity - accepted_quantity

    item.actual_quantity = actual_quantity
    item.accepted_quantity = accepted_quantity
    item.rejected_quantity = rejected_qty
    if unit_price_fen is not None:
        item.unit_price_fen = unit_price_fen
    if batch_no is not None:
        item.batch_no = batch_no
    if production_date is not None:
        item.production_date = production_date
    if expiry_date is not None:
        item.expiry_date = expiry_date
    if rejection_reason is not None:
        item.rejection_reason = rejection_reason

    # 更新状态
    if accepted_quantity <= Decimal("0"):
        item.status = ReceivingItemStatus.rejected.value
    elif rejected_qty > Decimal("0"):
        item.status = ReceivingItemStatus.partial.value
    else:
        item.status = ReceivingItemStatus.accepted.value

    # 收货单状态 → inspecting
    if order.status == ReceivingOrderStatus.draft.value:
        order.status = ReceivingOrderStatus.inspecting.value
        order.inspected_at = _now()

    await db.flush()

    logger.info(
        "receiving_item_inspected",
        order_id=order_id,
        item_id=item_id,
        accepted_quantity=float(accepted_quantity),
        rejected_quantity=float(rejected_qty),
        item_status=item.status,
    )

    return _item_to_dict(item)


# ─── 4. 完成验收（入库） ──────────────────────────────────


async def complete_receiving(
    order_id: str,
    tenant_id: str,
    store_id: str,
    db: AsyncSession,
    signer_id: Optional[str] = None,
) -> dict:
    """完成验收，将已验收数量入库。

    - 所有明细必须已完成验收（status != pending）
    - 对 accepted_quantity > 0 的明细，调用入库逻辑
    - 更新收货单状态为 fully_received 或 partially_received
    """
    await _set_tenant(db, tenant_id)

    q = (
        select(ReceivingOrder)
        .options(selectinload(ReceivingOrder.items))
        .where(
            ReceivingOrder.id == _uuid(order_id),
            ReceivingOrder.tenant_id == _uuid(tenant_id),
            ReceivingOrder.is_deleted == False,  # noqa: E712
        )
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"收货单 {order_id} 不存在")

    if order.status in (ReceivingOrderStatus.fully_received.value, ReceivingOrderStatus.rejected.value):
        raise ValueError(f"收货单已完成，状态：{order.status}")

    # 检查是否还有 pending 项
    pending_items = [i for i in order.items if i.status == ReceivingItemStatus.pending.value]
    if pending_items:
        raise ValueError(
            f"还有 {len(pending_items)} 项未完成验收（item_ids: {[str(i.id) for i in pending_items[:5]]}）"
        )

    # 执行入库
    received_count = 0
    rejected_count = 0
    inventory_results = []

    for item in order.items:
        if float(item.accepted_quantity or 0) > 0:
            result = await _process_item_to_inventory(
                item=item,
                order=order,
                store_id=store_id,
                tenant_id=tenant_id,
                db=db,
            )
            inventory_results.append(result)
            received_count += 1
        if float(item.rejected_quantity or 0) > 0:
            rejected_count += 1

    # 更新收货单
    order.received_items = received_count
    order.rejected_items = rejected_count
    order.signed_at = _now()
    if signer_id:
        order.receiver_id = _uuid(signer_id)

    if rejected_count == 0:
        order.status = ReceivingOrderStatus.fully_received.value
    elif received_count == 0:
        order.status = ReceivingOrderStatus.rejected.value
    else:
        order.status = ReceivingOrderStatus.partially_received.value

    await db.flush()

    logger.info(
        "receiving_order_completed",
        order_id=order_id,
        status=order.status,
        received_count=received_count,
        rejected_count=rejected_count,
        tenant_id=tenant_id,
    )

    # ── 事件总线：收货完成 ──────────────────────────────────
    if received_count > 0:
        asyncio.create_task(
            UniversalPublisher.publish(
                event_type=SupplyEventType.RECEIVING_COMPLETED,
                tenant_id=_uuid(tenant_id),
                store_id=order.store_id,
                entity_id=order.id,
                event_data={
                    "po_id": str(order.procurement_order_id) if order.procurement_order_id else None,
                    "supplier_id": str(order.supplier_id) if order.supplier_id else None,
                    "items_count": received_count,
                },
                source_service="tx-supply",
            )
        )

    # ── 事件总线：收货差异超5% ──────────────────────────────
    for item in order.items:
        expected = float(item.expected_quantity or 0)
        accepted = float(item.accepted_quantity or 0)
        if expected > 0:
            variance_pct = (expected - accepted) / expected
            if variance_pct > 0.05:
                variance_fen = round((expected - accepted) * (item.unit_price_fen or 0))
                asyncio.create_task(
                    UniversalPublisher.publish(
                        event_type=SupplyEventType.RECEIVING_VARIANCE,
                        tenant_id=_uuid(tenant_id),
                        store_id=order.store_id,
                        entity_id=order.id,
                        event_data={
                            "po_id": str(order.procurement_order_id) if order.procurement_order_id else None,
                            "ingredient_id": str(item.ingredient_id),
                            "variance_pct": round(variance_pct, 4),
                            "variance_fen": variance_fen,
                        },
                        source_service="tx-supply",
                    )
                )

    # ── 价格台账（v366）：每个有效入库的明细写一条价格快照 ──
    if order.supplier_id is not None:
        from .price_ledger_service import record_price as _record_price

        for item in order.items:
            if (
                item.unit_price_fen is None
                or float(item.accepted_quantity or 0) <= 0
            ):
                continue
            try:
                await _record_price(
                    tenant_id=tenant_id,
                    ingredient_id=str(item.ingredient_id),
                    supplier_id=str(order.supplier_id),
                    unit_price_fen=int(item.unit_price_fen),
                    db=db,
                    quantity_unit=getattr(item, "expected_unit", None)
                    or getattr(item, "unit", None),
                    captured_at=order.signed_at or _now(),
                    source_doc_type="receiving",
                    source_doc_id=str(order.id),
                    source_doc_no=getattr(order, "delivery_note_no", None)
                    or str(order.id)[:8],
                    store_id=str(order.store_id) if order.store_id else None,
                    notes="receiving v2 auto-captured",
                    created_by=signer_id,
                )
            except (ValueError, RuntimeError) as exc:
                # 价格快照失败不影响收货主流程
                logger.warning(
                    "price_ledger_record_failed",
                    order_id=order_id,
                    ingredient_id=str(item.ingredient_id),
                    error=str(exc),
                )

    return {
        "order_id": order_id,
        "status": order.status,
        "received_items": received_count,
        "rejected_items": rejected_count,
        "inventory_results": inventory_results,
    }


async def _process_item_to_inventory(
    item: ReceivingOrderItem,
    order: ReceivingOrder,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """将单项验收通过的数量写入库存。"""
    accepted_qty = float(item.accepted_quantity or 0)
    if accepted_qty <= 0:
        return {"ingredient_id": str(item.ingredient_id), "accepted": 0, "skipped": True}

    ing_result = await db.execute(
        select(Ingredient).where(
            Ingredient.id == item.ingredient_id,
            Ingredient.store_id == _uuid(store_id),
            Ingredient.tenant_id == _uuid(tenant_id),
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ingredient = ing_result.scalar_one_or_none()
    if ingredient is None:
        raise ValueError(f"原料 {item.ingredient_id}（{item.ingredient_name}）在门店 {store_id} 不存在，无法入库")

    qty_before = ingredient.current_quantity
    qty_after = qty_before + accepted_qty

    # 加权均价
    unit_price = item.unit_price_fen
    if unit_price is not None:
        if ingredient.unit_price_fen and qty_before > 0:
            total_cost = ingredient.unit_price_fen * qty_before + unit_price * accepted_qty
            ingredient.unit_price_fen = round(total_cost / qty_after)
        else:
            ingredient.unit_price_fen = unit_price

    ingredient.current_quantity = qty_after
    _update_ingredient_status(ingredient)

    # 创建库存流水
    import json

    notes_data: dict = {}
    if item.expiry_date:
        notes_data["expiry_date"] = item.expiry_date.isoformat()
    if item.production_date:
        notes_data["production_date"] = item.production_date.isoformat()
    notes_data["receiving_order_id"] = str(order.id)

    tx = IngredientTransaction(
        id=uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        ingredient_id=item.ingredient_id,
        store_id=_uuid(store_id),
        transaction_type=TransactionType.receiving.value,
        quantity=accepted_qty,
        unit_cost_fen=unit_price,
        total_cost_fen=round((unit_price or 0) * accepted_qty),
        quantity_before=qty_before,
        quantity_after=qty_after,
        reference_id=item.batch_no or str(order.id),
        notes=json.dumps(notes_data, ensure_ascii=False),
    )
    db.add(tx)
    await db.flush()

    # ── 库位级粒度入库（v367 TASK-2）──
    # 失败不影响主流程，仅记录 warning（货已入门店库存）
    location_info = await _try_allocate_to_location(
        ingredient=ingredient,
        accepted_qty=accepted_qty,
        batch_no=item.batch_no,
        expiry_date=item.expiry_date,
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )

    return {
        "ingredient_id": str(item.ingredient_id),
        "ingredient_name": item.ingredient_name,
        "accepted_quantity": accepted_qty,
        "qty_before": qty_before,
        "qty_after": qty_after,
        "transaction_id": str(tx.id),
        "location": location_info,
    }


async def _try_allocate_to_location(
    *,
    ingredient: Ingredient,
    accepted_qty: float,
    batch_no: Optional[str],
    expiry_date: Optional[date],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """尝试将本次入库写入库位粒度库存（inventory_by_location）。

    失败不抛出（只记 warning），保证收货主流程不被库位体系问题阻塞。
    场景：未配置库位/类目无温区映射 → 跳过；配置完整 → 成功落位。
    """
    # 延迟导入，避免循环依赖
    from decimal import Decimal as _Decimal

    from ..models.warehouse_location import AutoAllocateRequest as _AAR
    from . import warehouse_location_service as _wls

    try:
        req = _AAR(
            ingredient_id=str(ingredient.id),
            store_id=str(store_id),
            quantity=_Decimal(str(accepted_qty)),
            batch_no=batch_no,
            expiry_date=expiry_date,
            ingredient_category=getattr(ingredient, "category", None),
        )
        return await _wls.auto_allocate_location(
            body=req, tenant_id=tenant_id, db=db
        )
    except _wls.WarehouseLocationError as exc:
        logger.warning(
            "receiving_auto_allocate_skipped",
            ingredient_id=str(ingredient.id),
            reason=str(exc),
            tenant_id=tenant_id,
        )
        return {"skipped": True, "reason": str(exc)}
    except ProgrammingError as exc:
        logger.warning(
            "receiving_auto_allocate_db_unavailable",
            reason=str(exc),
        )
        return {"skipped": True, "reason": "warehouse_location tables not migrated"}


# ─── 5. 全部拒收 ─────────────────────────────────────────


async def reject_all(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    rejection_reason: Optional[str] = None,
) -> dict:
    """整批退货——将收货单及所有明细标记为 rejected。"""
    await _set_tenant(db, tenant_id)

    q = (
        select(ReceivingOrder)
        .options(selectinload(ReceivingOrder.items))
        .where(
            ReceivingOrder.id == _uuid(order_id),
            ReceivingOrder.tenant_id == _uuid(tenant_id),
            ReceivingOrder.is_deleted == False,  # noqa: E712
        )
    )
    order = (await db.execute(q)).scalar_one_or_none()
    if order is None:
        raise ValueError(f"收货单 {order_id} 不存在")
    if order.status in (ReceivingOrderStatus.fully_received.value, ReceivingOrderStatus.rejected.value):
        raise ValueError(f"收货单已完成，状态：{order.status}")

    for item in order.items:
        item.rejected_quantity = item.expected_quantity
        item.accepted_quantity = Decimal("0")
        item.status = ReceivingItemStatus.rejected.value
        if rejection_reason:
            item.rejection_reason = rejection_reason

    order.status = ReceivingOrderStatus.rejected.value
    order.rejected_items = len(order.items)
    order.received_items = 0
    order.signed_at = _now()
    await db.flush()

    logger.info(
        "receiving_order_rejected_all",
        order_id=order_id,
        tenant_id=tenant_id,
        item_count=len(order.items),
    )

    return {
        "order_id": order_id,
        "status": order.status,
        "rejected_items": len(order.items),
        "rejection_reason": rejection_reason,
    }


# ─── 内部 dict 转换 ───────────────────────────────────────


def _order_to_dict(o: ReceivingOrder) -> dict:
    return {
        "order_id": str(o.id),
        "store_id": str(o.store_id),
        "procurement_order_id": str(o.procurement_order_id) if o.procurement_order_id else None,
        "supplier_id": str(o.supplier_id) if o.supplier_id else None,
        "delivery_note_no": o.delivery_note_no,
        "status": o.status,
        "total_items": o.total_items,
        "received_items": o.received_items,
        "rejected_items": o.rejected_items,
        "receiver_id": str(o.receiver_id) if o.receiver_id else None,
        "inspected_at": o.inspected_at.isoformat() if o.inspected_at else None,
        "signed_at": o.signed_at.isoformat() if o.signed_at else None,
        "remarks": o.remarks,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _item_to_dict(i: ReceivingOrderItem) -> dict:
    return {
        "item_id": str(i.id),
        "receiving_order_id": str(i.receiving_order_id),
        "ingredient_id": str(i.ingredient_id),
        "ingredient_name": i.ingredient_name,
        "expected_quantity": float(i.expected_quantity or 0),
        "expected_unit": i.expected_unit,
        "actual_quantity": float(i.actual_quantity or 0),
        "accepted_quantity": float(i.accepted_quantity or 0),
        "rejected_quantity": float(i.rejected_quantity or 0),
        "unit_price_fen": i.unit_price_fen,
        "batch_no": i.batch_no,
        "production_date": i.production_date.isoformat() if i.production_date else None,
        "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
        "rejection_reason": i.rejection_reason,
        "status": i.status,
    }
