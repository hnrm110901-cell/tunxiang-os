"""入库出库服务 -- 原料批次库存管理核心

FIFO 先进先出扣料。金额单位：分（fen）。
批次通过 purchase 类型的 IngredientTransaction 记录跟踪，
reference_id 存批次号，notes 存 JSON 扩展信息（含 expiry_date）。
"""

import asyncio
import json
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import SupplyEventType, UniversalPublisher
from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus, TransactionType

from ..metrics import record_doc_number_fallback
from .doc_number_service import DocNumberError
from .doc_number_service import generate as gen_doc_number

logger = structlog.get_logger()


# ─── 内部工具 ───


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_ingredient(
    db: AsyncSession,
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
    lock: bool = False,
) -> Ingredient:
    """获取原料记录，不存在则抛出 ValueError

    Args:
        lock: True 时附加 FOR UPDATE 行锁 — mutation 路径必须显式传 lock=True 防并发丢更新
              （audit doc §4.3 Tier 1 修复，参考范本：tx-member stored_value_service.py）
    """
    stmt = select(Ingredient).where(
        Ingredient.id == _uuid(ingredient_id),
        Ingredient.store_id == _uuid(store_id),
        Ingredient.tenant_id == _uuid(tenant_id),
        Ingredient.is_deleted == False,  # noqa: E712
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    ing = result.scalar_one_or_none()
    if ing is None:
        raise ValueError(f"原料 {ingredient_id} 在门店 {store_id} 不存在")
    return ing


def _update_status(ingredient: Ingredient) -> str:
    """根据当前库存量更新状态"""
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


def _make_batch_notes(expiry_date: Optional[date], extra: Optional[dict] = None) -> str:
    """将批次扩展信息序列化为 JSON 字符串存入 notes"""
    data = extra or {}
    if expiry_date:
        data["expiry_date"] = expiry_date.isoformat()
    return json.dumps(data, ensure_ascii=False) if data else ""


def _parse_batch_notes(notes: Optional[str]) -> dict:
    """从 notes 解析 JSON 扩展信息"""
    if not notes:
        return {}
    try:
        return json.loads(notes)
    except (json.JSONDecodeError, TypeError):
        return {}


# ─── 入库 ───


async def receive_stock(
    ingredient_id: str,
    quantity: float,
    unit_cost_fen: int,
    batch_no: str,
    expiry_date: Optional[date],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    performed_by: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """入库（采购入库）

    创建 purchase 类型事务，更新库存数量。

    Args:
        now: 入库时间（默认当前 UTC，测试注入用）

    Returns: {"transaction_id": str, "new_quantity": float, "status": str, "doc_number": str|None}
    """
    if quantity <= 0:
        raise ValueError("入库数量必须大于0")
    if unit_cost_fen < 0:
        raise ValueError("单位成本不能为负数")

    await _set_tenant(db, tenant_id)

    # 生成可读单号（PRD-03 Wave1）— 失败 graceful degradation（doc_number 是辅助
    # 标识，infra 失败不阻塞 Tier 1 出入库业务，参考 issue #580 sequence gap 处理）
    doc_number: Optional[str] = None
    try:
        doc_number = await gen_doc_number(
            db, tenant_id=tenant_id, doc_type="inventory_io", now=now
        )
    except DocNumberError as e:
        logger.warning("doc_number_generate_skipped", reason=str(e))
    except Exception as e:  # noqa: BLE001 — 兜底，doc_number infra 异常不阻塞 Tier 1 业务
        logger.warning("doc_number_generate_failed_fallback_null", error=str(e), exc_info=True)
        record_doc_number_fallback(service="inventory_io", doc_type="inventory_io")
    # Tier 1 行锁（audit doc §4.3 P0）：防加权平均单价并发错算（毛利底线硬约束）
    ingredient = await _get_ingredient(db, ingredient_id, store_id, tenant_id, lock=True)

    qty_before = ingredient.current_quantity
    qty_after = qty_before + quantity
    ingredient.current_quantity = qty_after

    # 加权平均更新单价
    if ingredient.unit_price_fen and qty_before > 0:
        total_cost = ingredient.unit_price_fen * qty_before + unit_cost_fen * quantity
        ingredient.unit_price_fen = round(total_cost / qty_after)
    else:
        ingredient.unit_price_fen = unit_cost_fen

    status = _update_status(ingredient)

    tx = IngredientTransaction(
        id=uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        ingredient_id=_uuid(ingredient_id),
        store_id=_uuid(store_id),
        transaction_type=TransactionType.purchase.value,
        quantity=quantity,
        unit_cost_fen=unit_cost_fen,
        total_cost_fen=round(unit_cost_fen * quantity),
        quantity_before=qty_before,
        quantity_after=qty_after,
        performed_by=performed_by,
        reference_id=batch_no,
        notes=_make_batch_notes(expiry_date),
    )
    db.add(tx)
    await db.flush()

    # 写入 doc_number（ORM 实体冻结，用 raw SQL UPDATE）
    if doc_number is not None:
        await db.execute(
            text(
                "UPDATE ingredient_transactions SET doc_number = :doc_number WHERE id = :id"
            ),
            {"doc_number": doc_number, "id": str(tx.id)},
        )

    logger.info(
        "stock_received",
        ingredient_id=ingredient_id,
        batch_no=batch_no,
        doc_number=doc_number,
        quantity=quantity,
        unit_cost_fen=unit_cost_fen,
        new_quantity=qty_after,
        store_id=store_id,
        tenant_id=tenant_id,
    )

    return {
        "transaction_id": str(tx.id),
        "doc_number": doc_number,
        "new_quantity": qty_after,
        "status": status,
    }


# ─── 出库（FIFO） ───


async def _get_batch_remaining(
    db: AsyncSession,
    ingredient_id: str,
    tenant_id: str,
    store_id: str,
) -> list[dict]:
    """获取各批次剩余数量，按入库时间升序（FIFO）

    逻辑：每个批次（reference_id）的 purchase 入库总量 - 同批次 usage/waste/transfer 出库总量
    """
    tid = _uuid(tenant_id)
    iid = _uuid(ingredient_id)
    sid = _uuid(store_id)

    # 获取所有 purchase 事务作为批次来源
    purchase_q = (
        select(
            IngredientTransaction.reference_id,
            IngredientTransaction.notes,
            IngredientTransaction.unit_cost_fen,
            IngredientTransaction.quantity.label("in_qty"),
            IngredientTransaction.created_at,
        )
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.ingredient_id == iid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type == TransactionType.purchase.value,
            IngredientTransaction.is_deleted == False,  # noqa: E712
        )
        .order_by(IngredientTransaction.created_at.asc())
    )
    purchases_result = await db.execute(purchase_q)
    purchases = purchases_result.all()

    # 获取所有出库事务（按批次分组）
    out_types = [
        TransactionType.usage.value,
        TransactionType.waste.value,
        TransactionType.transfer.value,
    ]
    out_q = (
        select(
            IngredientTransaction.reference_id,
            func.sum(IngredientTransaction.quantity).label("out_total"),
        )
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.ingredient_id == iid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type.in_(out_types),
            IngredientTransaction.is_deleted == False,  # noqa: E712
        )
        .group_by(IngredientTransaction.reference_id)
    )
    out_result = await db.execute(out_q)
    out_map: dict[str, float] = {row.reference_id: float(row.out_total) for row in out_result.all()}

    batches = []
    for p in purchases:
        batch_no = p.reference_id or ""
        used = out_map.get(batch_no, 0.0)
        remaining = float(p.in_qty) - used
        if remaining > 0.001:  # 浮点精度
            notes_data = _parse_batch_notes(p.notes)
            expiry_str = notes_data.get("expiry_date")
            expiry = date.fromisoformat(expiry_str) if expiry_str else None
            batches.append(
                {
                    "batch_no": batch_no,
                    "remaining": remaining,
                    "unit_cost_fen": p.unit_cost_fen,
                    "expiry_date": expiry,
                    "created_at": p.created_at,
                }
            )
    return batches


async def issue_stock(
    ingredient_id: str,
    quantity: float,
    reason: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    performed_by: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> dict:
    """出库（FIFO 先进先出）

    reason: "usage" | "waste" | "transfer"
    按最早批次优先扣料，生成多条出库事务（每个被扣的批次一条）。
    Returns: {"transactions": [...], "new_quantity": float, "status": str}
    """
    if quantity <= 0:
        raise ValueError("出库数量必须大于0")

    valid_reasons = {TransactionType.usage.value, TransactionType.waste.value, TransactionType.transfer.value}
    if reason not in valid_reasons:
        raise ValueError(f"出库原因必须是 {valid_reasons} 之一")

    await _set_tenant(db, tenant_id)

    # 生成报废单可读单号（PRD-03 Wave2）— 仅 waste reason 分配单号；
    # "usage" 不需要单号；"transfer" 由 transfer_service 主单号承载，子流水留 NULL。
    # 失败 graceful degradation（辅助标识 infra 失败不阻塞 Tier 1 出库业务）
    doc_number: Optional[str] = None
    if reason == TransactionType.waste.value:
        try:
            doc_number = await gen_doc_number(
                db, tenant_id=tenant_id, doc_type="waste", now=datetime.now(timezone.utc)
            )
        except DocNumberError as e:
            logger.warning("doc_number_generate_skipped", reason=str(e))
        except Exception as e:  # noqa: BLE001 — doc_number 是辅助标识 infra fallback，参考 feedback_graceful_degradation_pattern.md
            logger.warning("doc_number_generate_failed_fallback_null", error=str(e), exc_info=True)
            record_doc_number_fallback(service="inventory_io", doc_type="waste")

    # Tier 1 行锁（audit doc §4.3 P0）：防 FIFO 出库并发丢更新（食安/成本）
    ingredient = await _get_ingredient(db, ingredient_id, store_id, tenant_id, lock=True)

    if ingredient.current_quantity < quantity:
        raise ValueError(f"库存不足: 当前 {ingredient.current_quantity}, 需求 {quantity}")

    batches = await _get_batch_remaining(db, ingredient_id, tenant_id, store_id)
    if not batches:
        raise ValueError("无可用批次库存")

    remaining_to_issue = quantity
    qty_before = ingredient.current_quantity
    transactions = []

    for batch in batches:
        if remaining_to_issue <= 0.001:
            break

        deduct = min(batch["remaining"], remaining_to_issue)
        remaining_to_issue -= deduct

        tx = IngredientTransaction(
            id=uuid.uuid4(),
            tenant_id=_uuid(tenant_id),
            ingredient_id=_uuid(ingredient_id),
            store_id=_uuid(store_id),
            transaction_type=reason,
            quantity=deduct,
            unit_cost_fen=batch["unit_cost_fen"],
            total_cost_fen=round((batch["unit_cost_fen"] or 0) * deduct),
            quantity_before=ingredient.current_quantity,
            quantity_after=ingredient.current_quantity - deduct,
            performed_by=performed_by,
            reference_id=batch["batch_no"],
            notes=reference_id or "",
        )
        ingredient.current_quantity -= deduct
        db.add(tx)
        transactions.append(
            {
                "transaction_id": str(tx.id),
                "batch_no": batch["batch_no"],
                "deducted": deduct,
                "unit_cost_fen": batch["unit_cost_fen"],
            }
        )

    await db.flush()
    status = _update_status(ingredient)

    # 写入 doc_number（ORM 实体冻结，用 raw SQL UPDATE，同 receive_stock 模式）
    # ANY(:ids::uuid[]) 单条 SQL 覆盖所有 batch，N→1 round-trip（与 Wave1 receive_stock 风格一致）
    if doc_number is not None and transactions:
        tx_ids = [t["transaction_id"] for t in transactions]
        await db.execute(
            text(
                "UPDATE ingredient_transactions SET doc_number = :doc_number"
                " WHERE id = ANY(:ids::uuid[])"
            ),
            {"doc_number": doc_number, "ids": tx_ids},
        )

    logger.info(
        "stock_issued",
        ingredient_id=ingredient_id,
        reason=reason,
        doc_number=doc_number,
        total_quantity=quantity,
        batches_affected=len(transactions),
        new_quantity=ingredient.current_quantity,
        store_id=store_id,
        tenant_id=tenant_id,
    )

    # ── 事件总线：出库后库存触底检测 ────────────────────────
    if status in (InventoryStatus.low.value, InventoryStatus.critical.value, InventoryStatus.out_of_stock.value):
        asyncio.create_task(
            UniversalPublisher.publish(
                event_type=SupplyEventType.STOCK_LOW,
                tenant_id=_uuid(tenant_id),
                store_id=_uuid(store_id),
                entity_id=_uuid(ingredient_id),
                event_data={
                    "ingredient_id": ingredient_id,
                    "current_qty": ingredient.current_quantity,
                    "threshold_qty": ingredient.min_quantity,
                    "unit": ingredient.unit,
                },
                source_service="tx-supply",
            )
        )

    return {
        "transactions": transactions,
        "new_quantity": ingredient.current_quantity,
        "status": status,
        "doc_number": doc_number,
    }


# ─── 盘点调整 ───


async def adjust_stock(
    ingredient_id: str,
    quantity: float,
    reason: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    performed_by: Optional[str] = None,
) -> dict:
    """盘盈盘亏调整

    quantity > 0 → 盘盈，quantity < 0 → 盘亏。
    Returns: {"transaction_id": str, "new_quantity": float, "status": str}
    """
    if quantity == 0:
        raise ValueError("调整数量不能为0")

    await _set_tenant(db, tenant_id)

    # 生成盘点调整单可读单号（PRD-03 Wave2）— 失败 graceful degradation（辅助标识 infra 失败
    # 不阻塞 Tier 1 盘点调整业务，参考 feedback_graceful_degradation_pattern.md）
    doc_number: Optional[str] = None
    try:
        doc_number = await gen_doc_number(
            db, tenant_id=tenant_id, doc_type="adjustment", now=datetime.now(timezone.utc)
        )
    except DocNumberError as e:
        logger.warning("doc_number_generate_skipped", reason=str(e))
    except Exception as e:  # noqa: BLE001 — doc_number 是辅助标识 infra fallback，参考 feedback_graceful_degradation_pattern.md
        logger.warning("doc_number_generate_failed_fallback_null", error=str(e), exc_info=True)
        record_doc_number_fallback(service="inventory_io", doc_type="adjustment")

    # Tier 1 行锁（audit doc §4.3 P1）：盘点调整与日常 IO 并发丢更新，与其他 mutation 路径统一
    ingredient = await _get_ingredient(db, ingredient_id, store_id, tenant_id, lock=True)

    qty_before = ingredient.current_quantity
    qty_after = qty_before + quantity

    if qty_after < 0:
        raise ValueError(f"调整后库存为负: {qty_before} + ({quantity}) = {qty_after}")

    ingredient.current_quantity = qty_after
    status = _update_status(ingredient)

    tx = IngredientTransaction(
        id=uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        ingredient_id=_uuid(ingredient_id),
        store_id=_uuid(store_id),
        transaction_type=TransactionType.adjustment.value,
        quantity=quantity,
        unit_cost_fen=ingredient.unit_price_fen,
        total_cost_fen=round((ingredient.unit_price_fen or 0) * abs(quantity)),
        quantity_before=qty_before,
        quantity_after=qty_after,
        performed_by=performed_by,
        reference_id=None,
        notes=reason,
    )
    db.add(tx)
    await db.flush()

    # 写入 doc_number（ORM 实体冻结，用 raw SQL UPDATE，同 receive_stock 模式）
    if doc_number is not None:
        await db.execute(
            text(
                "UPDATE ingredient_transactions SET doc_number = :doc_number WHERE id = :id"
            ),
            {"doc_number": doc_number, "id": str(tx.id)},
        )

    logger.info(
        "stock_adjusted",
        ingredient_id=ingredient_id,
        adjustment=quantity,
        reason=reason,
        doc_number=doc_number,
        new_quantity=qty_after,
        store_id=store_id,
        tenant_id=tenant_id,
    )

    return {
        "transaction_id": str(tx.id),
        "new_quantity": qty_after,
        "status": status,
        "doc_number": doc_number,
    }


# ─── 查询 ───


async def get_stock_balance(
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取单个原料的库存余额 + 批次明细

    Returns: {quantity, unit, avg_cost_fen, batches: [{batch_no, qty, expiry}]}
    """
    await _set_tenant(db, tenant_id)
    ingredient = await _get_ingredient(db, ingredient_id, store_id, tenant_id)
    batches = await _get_batch_remaining(db, ingredient_id, tenant_id, store_id)

    batch_list = []
    total_cost = 0
    total_qty = 0.0
    for b in batches:
        batch_list.append(
            {
                "batch_no": b["batch_no"],
                "qty": b["remaining"],
                "expiry": b["expiry_date"].isoformat() if b["expiry_date"] else None,
                "unit_cost_fen": b["unit_cost_fen"],
            }
        )
        total_qty += b["remaining"]
        total_cost += (b["unit_cost_fen"] or 0) * b["remaining"]

    avg_cost = round(total_cost / total_qty) if total_qty > 0 else 0

    return {
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient.ingredient_name,
        "quantity": ingredient.current_quantity,
        "unit": ingredient.unit,
        "avg_cost_fen": avg_cost,
        "status": ingredient.status,
        "batches": batch_list,
    }


async def get_store_inventory(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 50,
) -> dict:
    """门店全部库存清单

    Returns: {items: [...], total: int}
    """
    await _set_tenant(db, tenant_id)
    sid = _uuid(store_id)
    tid = _uuid(tenant_id)

    base_filter = and_(
        Ingredient.tenant_id == tid,
        Ingredient.store_id == sid,
        Ingredient.is_deleted == False,  # noqa: E712
    )

    count_q = select(func.count(Ingredient.id)).where(base_filter)
    total = (await db.execute(count_q)).scalar() or 0

    items_q = (
        select(Ingredient).where(base_filter).order_by(Ingredient.ingredient_name).offset((page - 1) * size).limit(size)
    )
    result = await db.execute(items_q)
    ingredients = result.scalars().all()

    items = []
    for ing in ingredients:
        items.append(
            {
                "id": str(ing.id),
                "ingredient_name": ing.ingredient_name,
                "category": ing.category,
                "unit": ing.unit,
                "current_quantity": ing.current_quantity,
                "min_quantity": ing.min_quantity,
                "max_quantity": ing.max_quantity,
                "unit_price_fen": ing.unit_price_fen,
                "status": ing.status,
                "supplier_name": ing.supplier_name,
            }
        )

    return {"items": items, "total": total}
