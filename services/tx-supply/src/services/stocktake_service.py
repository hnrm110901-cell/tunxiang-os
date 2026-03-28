"""盘点服务 -- 系统库存 vs 实盘对比 -> 差异报告

流程：
1. create_stocktake  -> 创建盘点单，快照当前系统库存
2. record_count      -> 逐条录入实盘数量
3. finalize_stocktake -> 计算差异，生成 adjustment 流水，更新库存

金额单位：分(fen)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, func, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部盘点状态存储（后续可迁移至 stocktakes 表）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 内存缓存（用于 MVP 阶段；生产环境应建 stocktakes + stocktake_items 表）
_stocktakes: dict[str, dict[str, Any]] = {}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _calc_status(current: float, min_qty: float) -> str:
    if current <= 0:
        return InventoryStatus.out_of_stock.value
    if current <= min_qty * 0.3:
        return InventoryStatus.critical.value
    if current <= min_qty:
        return InventoryStatus.low.value
    return InventoryStatus.normal.value


# ─── 创建盘点单 ───


async def create_stocktake(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建盘点单，快照当前系统库存

    Returns:
        {stocktake_id, store_id, status, item_count, items: [...]}
    """
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    await _set_tenant(db, tenant_id)

    # 查询门店所有未删除的库存原料
    result = await db.execute(
        select(Ingredient)
        .where(Ingredient.tenant_id == tenant_uuid)
        .where(Ingredient.store_id == store_uuid)
        .where(Ingredient.is_deleted == False)  # noqa: E712
        .order_by(Ingredient.ingredient_name)
    )
    ingredients = result.scalars().all()

    stocktake_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    items: dict[str, dict[str, Any]] = {}
    for ing in ingredients:
        items[str(ing.id)] = {
            "ingredient_id": str(ing.id),
            "ingredient_name": ing.ingredient_name,
            "category": ing.category,
            "unit": ing.unit,
            "system_qty": ing.current_quantity,
            "actual_qty": None,  # 待录入
            "unit_price_fen": ing.unit_price_fen,
        }

    stocktake = {
        "stocktake_id": stocktake_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "status": "open",
        "created_at": now,
        "items": items,
    }
    _stocktakes[stocktake_id] = stocktake

    log.info("stocktake.created", stocktake_id=stocktake_id, item_count=len(items))

    return {
        "ok": True,
        "stocktake_id": stocktake_id,
        "store_id": store_id,
        "status": "open",
        "item_count": len(items),
        "items": [
            {
                "ingredient_id": v["ingredient_id"],
                "ingredient_name": v["ingredient_name"],
                "unit": v["unit"],
                "system_qty": v["system_qty"],
            }
            for v in items.values()
        ],
    }


# ─── 录入实盘数量 ───


async def record_count(
    stocktake_id: str,
    ingredient_id: str,
    actual_qty: float,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """录入单条原料的实盘数量

    Returns:
        {ok, ingredient_id, ingredient_name, system_qty, actual_qty, variance}
    """
    stocktake = _stocktakes.get(stocktake_id)
    if not stocktake:
        return {"ok": False, "error": f"Stocktake {stocktake_id} not found"}

    if stocktake["tenant_id"] != tenant_id:
        return {"ok": False, "error": "Tenant mismatch"}

    if stocktake["status"] != "open":
        return {"ok": False, "error": f"Stocktake is {stocktake['status']}, not open"}

    item = stocktake["items"].get(ingredient_id)
    if not item:
        return {"ok": False, "error": f"Ingredient {ingredient_id} not in stocktake"}

    item["actual_qty"] = actual_qty
    variance = actual_qty - item["system_qty"]

    log.info(
        "stocktake.count_recorded",
        stocktake_id=stocktake_id,
        ingredient_name=item["ingredient_name"],
        system_qty=item["system_qty"],
        actual_qty=actual_qty,
        variance=variance,
    )

    return {
        "ok": True,
        "ingredient_id": ingredient_id,
        "ingredient_name": item["ingredient_name"],
        "system_qty": item["system_qty"],
        "actual_qty": actual_qty,
        "variance": round(variance, 4),
    }


# ─── 完成盘点 ───


async def finalize_stocktake(
    stocktake_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """完成盘点：对比系统库存 vs 实盘，生成差异报告和库存调整

    Returns:
        {
            stocktake_id, status,
            total_items, counted, uncounted,
            matched, surplus, deficit,
            deficit_cost_fen, surplus_cost_fen,
            details: [...]
        }
    """
    stocktake = _stocktakes.get(stocktake_id)
    if not stocktake:
        return {"ok": False, "error": f"Stocktake {stocktake_id} not found"}

    if stocktake["tenant_id"] != tenant_id:
        return {"ok": False, "error": "Tenant mismatch"}

    if stocktake["status"] != "open":
        return {"ok": False, "error": f"Stocktake already {stocktake['status']}"}

    tenant_uuid = uuid.UUID(tenant_id)
    await _set_tenant(db, tenant_id)

    total_items = len(stocktake["items"])
    matched = 0
    surplus = 0
    deficit = 0
    uncounted = 0
    deficit_cost_fen = 0
    surplus_cost_fen = 0
    details: list[dict[str, Any]] = []

    async with db.begin_nested():
        for ing_id, item in stocktake["items"].items():
            actual_qty = item.get("actual_qty")

            if actual_qty is None:
                uncounted += 1
                continue

            system_qty = item["system_qty"]
            variance = round(actual_qty - system_qty, 4)
            unit_price = item.get("unit_price_fen") or 0

            if abs(variance) < 0.001:
                # 匹配
                matched += 1
                status = "matched"
            elif variance > 0:
                surplus += 1
                surplus_cost_fen += int(variance * unit_price)
                status = "surplus"
            else:
                deficit += 1
                deficit_cost_fen += int(abs(variance) * unit_price)
                status = "deficit"

            # 创建调整流水 + 更新库存（仅差异 != 0 时）
            if abs(variance) >= 0.001:
                ing_uuid = uuid.UUID(ing_id)
                ing_result = await db.execute(
                    select(Ingredient)
                    .where(Ingredient.id == ing_uuid)
                    .where(Ingredient.tenant_id == tenant_uuid)
                    .where(Ingredient.is_deleted == False)  # noqa: E712
                )
                ingredient = ing_result.scalar_one_or_none()
                if ingredient:
                    old_qty = ingredient.current_quantity
                    ingredient.current_quantity = actual_qty
                    ingredient.status = _calc_status(actual_qty, ingredient.min_quantity)

                    txn = IngredientTransaction(
                        id=uuid.uuid4(),
                        tenant_id=tenant_uuid,
                        ingredient_id=ing_uuid,
                        store_id=uuid.UUID(stocktake["store_id"]),
                        transaction_type="adjustment",
                        quantity=variance,
                        unit_cost_fen=unit_price if unit_price else None,
                        total_cost_fen=int(abs(variance) * unit_price) if unit_price else None,
                        quantity_before=old_qty,
                        quantity_after=actual_qty,
                        performed_by="stocktake",
                        reference_id=stocktake_id,
                        notes=f"盘点调整: {item['ingredient_name']} 系统={system_qty} 实盘={actual_qty}",
                    )
                    db.add(txn)

            details.append({
                "ingredient_id": ing_id,
                "ingredient_name": item["ingredient_name"],
                "unit": item["unit"],
                "system_qty": system_qty,
                "actual_qty": actual_qty,
                "variance": variance,
                "variance_cost_fen": int(abs(variance) * unit_price),
                "status": status,
            })

    await db.flush()

    stocktake["status"] = "finalized"
    stocktake["finalized_at"] = datetime.now(timezone.utc).isoformat()

    counted = total_items - uncounted

    log.info(
        "stocktake.finalized",
        stocktake_id=stocktake_id,
        total=total_items,
        matched=matched,
        surplus=surplus,
        deficit=deficit,
        deficit_cost_fen=deficit_cost_fen,
    )

    return {
        "ok": True,
        "stocktake_id": stocktake_id,
        "status": "finalized",
        "total_items": total_items,
        "counted": counted,
        "uncounted": uncounted,
        "matched": matched,
        "surplus": surplus,
        "deficit": deficit,
        "deficit_cost_fen": deficit_cost_fen,
        "surplus_cost_fen": surplus_cost_fen,
        "details": details,
    }


# ─── 历史盘点列表 ───


async def get_stocktake_history(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """获取指定门店的历史盘点列表

    Returns:
        {ok, stocktakes: [{stocktake_id, status, created_at, item_count, ...}]}
    """
    records = [
        {
            "stocktake_id": st["stocktake_id"],
            "store_id": st["store_id"],
            "status": st["status"],
            "created_at": st["created_at"],
            "finalized_at": st.get("finalized_at"),
            "item_count": len(st["items"]),
        }
        for st in _stocktakes.values()
        if st["store_id"] == store_id and st["tenant_id"] == tenant_id
    ]

    # 按创建时间倒序
    records.sort(key=lambda x: x["created_at"], reverse=True)

    return {"ok": True, "stocktakes": records}
