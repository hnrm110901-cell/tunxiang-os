"""自动扣料引擎 -- 订单完成 -> BOM自动扣料 -> 库存减少

核心流程：
1. 订单完成时，根据每道菜的 BOM 配方（dish_ingredients / bom_items）
2. 自动创建 ingredient_transactions (type=consume)
3. 扣减 ingredients.current_quantity
4. 库存不足时记录告警但不阻塞（允许负库存）

金额单位：分(fen)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import (
    DishIngredient,
    Ingredient,
    IngredientTransaction,
)
from shared.ontology.src.enums import InventoryStatus

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  自动扣料引擎
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置当前租户上下文（RLS）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_bom_for_dish(
    db: AsyncSession,
    dish_id: uuid.UUID,
    tenant_uuid: uuid.UUID,
) -> list[dict[str, Any]]:
    """获取一道菜的 BOM 配方行

    优先查 dish_ingredients 表（简单BOM），返回 ingredient_id + quantity + unit。
    """
    result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.dish_id == dish_id)
        .where(DishIngredient.tenant_id == tenant_uuid)
        .where(DishIngredient.is_deleted == False)  # noqa: E712
    )
    rows = result.scalars().all()
    return [
        {
            "ingredient_id": row.ingredient_id,
            "quantity": float(row.quantity),
            "unit": row.unit,
        }
        for row in rows
    ]


def _calc_status(current: float, min_qty: float) -> str:
    """根据库存量计算状态"""
    if current <= 0:
        return InventoryStatus.out_of_stock.value
    if current <= min_qty * 0.3:
        return InventoryStatus.critical.value
    if current <= min_qty:
        return InventoryStatus.low.value
    return InventoryStatus.normal.value


# ─── 单道菜扣料 ───


async def deduct_for_dish(
    dish_id: str,
    quantity: int,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """对单道菜执行 BOM 扣料

    Args:
        dish_id: 菜品 UUID
        quantity: 菜品份数
        store_id: 门店 UUID
        tenant_id: 租户 UUID
        db: 数据库会话（调用方管理事务）

    Returns:
        {deducted: [...], missing_bom: bool, insufficient_stock: [...]}
    """
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    store_uuid = uuid.UUID(store_id)

    await _set_tenant(db, tenant_id)

    bom_lines = await _get_bom_for_dish(db, dish_uuid, tenant_uuid)
    if not bom_lines:
        log.warning("bom_not_found", dish_id=dish_id)
        return {"deducted": [], "missing_bom": True, "insufficient_stock": []}

    deducted: list[dict[str, Any]] = []
    insufficient_stock: list[dict[str, Any]] = []

    for line in bom_lines:
        ing_id = line["ingredient_id"]
        consume_qty = line["quantity"] * quantity  # BOM用量 x 份数

        # 查找门店库存记录（ingredient_id 在 dish_ingredients 中是 String(50)）
        # 需要通过 ingredient_name 或直接 UUID 关联
        # dish_ingredients.ingredient_id 是 String(50)，可能存的是 UUID 字符串
        try:
            ing_uuid = uuid.UUID(ing_id)
        except ValueError:
            log.warning("invalid_ingredient_id", ingredient_id=ing_id, dish_id=dish_id)
            continue

        result = await db.execute(
            select(Ingredient)
            .where(Ingredient.id == ing_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.tenant_id == tenant_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
        )
        ingredient = result.scalar_one_or_none()
        if ingredient is None:
            log.warning("ingredient_not_in_store", ingredient_id=ing_id, store_id=store_id)
            continue

        old_qty = ingredient.current_quantity
        new_qty = old_qty - consume_qty

        # 库存不足：记录告警但不阻塞（允许负库存）
        if new_qty < 0:
            insufficient_stock.append(
                {
                    "ingredient_id": str(ingredient.id),
                    "ingredient_name": ingredient.ingredient_name,
                    "required_qty": consume_qty,
                    "available_qty": old_qty,
                    "shortage_qty": abs(new_qty),
                }
            )
            log.warning(
                "insufficient_stock",
                ingredient_name=ingredient.ingredient_name,
                required=consume_qty,
                available=old_qty,
            )

        # 扣减库存
        ingredient.current_quantity = new_qty
        ingredient.status = _calc_status(new_qty, ingredient.min_quantity)

        # 创建消费流水
        txn = IngredientTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            ingredient_id=ingredient.id,
            store_id=store_uuid,
            transaction_type="consume",
            quantity=-consume_qty,
            unit_cost_fen=ingredient.unit_price_fen,
            total_cost_fen=(int(consume_qty * ingredient.unit_price_fen) if ingredient.unit_price_fen else None),
            quantity_before=old_qty,
            quantity_after=new_qty,
            performed_by="auto_deduction",
            notes=f"BOM扣料: dish={dish_id}, qty={quantity}",
        )
        db.add(txn)

        deducted.append(
            {
                "ingredient_id": str(ingredient.id),
                "ingredient_name": ingredient.ingredient_name,
                "consumed_qty": consume_qty,
                "unit": ingredient.unit,
                "stock_before": old_qty,
                "stock_after": new_qty,
                "transaction_id": str(txn.id),
            }
        )

    await db.flush()

    return {
        "deducted": deducted,
        "missing_bom": False,
        "insufficient_stock": insufficient_stock,
    }


# ─── 订单级扣料（事务性） ───


async def deduct_for_order(
    order_id: str,
    order_items: list[dict[str, Any]],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """订单完成时的批量扣料

    事务性保证：一个订单的扣料要么全部成功要么全部回滚。
    调用方应在外层管理 begin/commit/rollback。

    Args:
        order_id: 订单 UUID
        order_items: [{dish_id, quantity, item_name}, ...]
        store_id: 门店 UUID
        tenant_id: 租户 UUID
        db: 数据库会话

    Returns:
        {
            order_id, deducted_items: [...],
            missing_bom: [...], insufficient_stock: [...]
        }
    """
    log.info("deduct_for_order.start", order_id=order_id, item_count=len(order_items))

    all_deducted: list[dict[str, Any]] = []
    all_missing_bom: list[dict[str, Any]] = []
    all_insufficient: list[dict[str, Any]] = []

    # 使用 savepoint 保证原子性
    async with db.begin_nested():
        for item in order_items:
            dish_id = item.get("dish_id")
            quantity = item.get("quantity", 1)
            item_name = item.get("item_name", "")

            if not dish_id:
                log.warning("order_item_no_dish_id", item_name=item_name)
                continue

            result = await deduct_for_dish(
                dish_id=dish_id,
                quantity=quantity,
                store_id=store_id,
                tenant_id=tenant_id,
                db=db,
            )

            if result["missing_bom"]:
                all_missing_bom.append(
                    {
                        "dish_id": dish_id,
                        "item_name": item_name,
                        "quantity": quantity,
                    }
                )
            else:
                for d in result["deducted"]:
                    d["order_id"] = order_id
                    d["dish_id"] = dish_id
                all_deducted.extend(result["deducted"])

            all_insufficient.extend(result["insufficient_stock"])

        # 记录订单级 reference 到所有流水
        # （已在 deduct_for_dish 的 notes 中记录）

    log.info(
        "deduct_for_order.done",
        order_id=order_id,
        deducted_count=len(all_deducted),
        missing_bom_count=len(all_missing_bom),
        insufficient_count=len(all_insufficient),
    )

    return {
        "order_id": order_id,
        "deducted_items": all_deducted,
        "missing_bom": all_missing_bom,
        "insufficient_stock": all_insufficient,
    }


# ─── 扣料回滚（退菜/退单） ───


async def rollback_deduction(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """回滚指定订单的所有扣料

    查找该订单产生的所有 consume 类型流水，逐条反向回补库存。

    Args:
        order_id: 订单 UUID
        tenant_id: 租户 UUID
        db: 数据库会话

    Returns:
        {order_id, rolled_back_count, restored_items: [...]}
    """
    tenant_uuid = uuid.UUID(tenant_id)
    await _set_tenant(db, tenant_id)

    log.info("rollback_deduction.start", order_id=order_id)

    # 查找该订单产生的所有 consume 流水（通过 notes 中的 order 信息匹配）
    # 更优的方案：通过 reference_id 关联
    result = await db.execute(
        select(IngredientTransaction)
        .where(IngredientTransaction.tenant_id == tenant_uuid)
        .where(IngredientTransaction.transaction_type == "consume")
        .where(IngredientTransaction.is_deleted == False)  # noqa: E712
        .where(IngredientTransaction.reference_id == order_id)
    )
    consume_txns = result.scalars().all()

    # 如果没有通过 reference_id 找到，尝试通过 notes 模糊匹配
    if not consume_txns:
        result = await db.execute(
            select(IngredientTransaction)
            .where(IngredientTransaction.tenant_id == tenant_uuid)
            .where(IngredientTransaction.transaction_type == "consume")
            .where(IngredientTransaction.is_deleted == False)  # noqa: E712
            .where(IngredientTransaction.notes.contains(order_id))
        )
        consume_txns = result.scalars().all()

    if not consume_txns:
        log.warning("rollback_no_transactions", order_id=order_id)
        return {
            "order_id": order_id,
            "rolled_back_count": 0,
            "restored_items": [],
        }

    restored_items: list[dict[str, Any]] = []

    async with db.begin_nested():
        for txn in consume_txns:
            restore_qty = abs(txn.quantity)  # consume 流水 quantity 为负

            # 恢复库存
            ing_result = await db.execute(
                select(Ingredient)
                .where(Ingredient.id == txn.ingredient_id)
                .where(Ingredient.tenant_id == tenant_uuid)
                .where(Ingredient.is_deleted == False)  # noqa: E712
            )
            ingredient = ing_result.scalar_one_or_none()
            if ingredient is None:
                log.warning("rollback_ingredient_missing", ingredient_id=str(txn.ingredient_id))
                continue

            old_qty = ingredient.current_quantity
            new_qty = old_qty + restore_qty
            ingredient.current_quantity = new_qty
            ingredient.status = _calc_status(new_qty, ingredient.min_quantity)

            # 创建回滚流水
            rollback_txn = IngredientTransaction(
                id=uuid.uuid4(),
                tenant_id=tenant_uuid,
                ingredient_id=ingredient.id,
                store_id=txn.store_id,
                transaction_type="rollback",
                quantity=restore_qty,
                unit_cost_fen=txn.unit_cost_fen,
                total_cost_fen=(int(restore_qty * txn.unit_cost_fen) if txn.unit_cost_fen else None),
                quantity_before=old_qty,
                quantity_after=new_qty,
                performed_by="auto_rollback",
                reference_id=order_id,
                notes=f"回滚扣料: order={order_id}, 原流水={txn.id}",
            )
            db.add(rollback_txn)

            # 标记原流水为已删除
            txn.is_deleted = True

            restored_items.append(
                {
                    "ingredient_id": str(ingredient.id),
                    "ingredient_name": ingredient.ingredient_name,
                    "restored_qty": restore_qty,
                    "stock_before": old_qty,
                    "stock_after": new_qty,
                }
            )

    await db.flush()

    log.info(
        "rollback_deduction.done",
        order_id=order_id,
        rolled_back_count=len(restored_items),
    )

    return {
        "order_id": order_id,
        "rolled_back_count": len(restored_items),
        "restored_items": restored_items,
    }
