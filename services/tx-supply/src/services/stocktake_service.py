"""盘点服务 -- 系统库存 vs 实盘对比 -> 差异报告

流程：
1. create_stocktake  -> 创建盘点单，快照当前系统库存
2. record_count      -> 逐条录入实盘数量
3. finalize_stocktake -> 计算差异，生成 adjustment 流水，更新库存

金额单位：分(fen)

持久化层：
- stocktakes 表 — 盘点单头
- stocktake_items 表 — 盘点明细（每原料一行）
- 若 v064 迁移未运行（表不存在），自动降级到内存模式并记录 WARNING
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, text, and_, update
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内存降级存储（仅在 v064 迁移未运行时使用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_stocktakes: dict[str, dict[str, Any]] = {}
_db_mode: Optional[bool] = None  # None=未检测, True=DB模式, False=内存模式


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _check_db_mode(db: AsyncSession) -> bool:
    """检测 stocktakes 表是否存在（v064 迁移是否已运行）"""
    global _db_mode
    if _db_mode is not None:
        return _db_mode
    try:
        await db.execute(text("SELECT 1 FROM stocktakes LIMIT 1"))
        _db_mode = True
        log.info("stocktake_service.mode", mode="db")
    except (ProgrammingError, OperationalError):
        _db_mode = False
        log.warning(
            "stocktake_service.fallback_to_memory",
            reason="stocktakes table not found — run v064_wms_persistence migration",
        )
    return _db_mode


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
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    items: dict[str, dict[str, Any]] = {}
    for ing in ingredients:
        items[str(ing.id)] = {
            "ingredient_id": str(ing.id),
            "ingredient_name": ing.ingredient_name,
            "category": ing.category,
            "unit": ing.unit,
            "system_qty": ing.current_quantity,
            "actual_qty": None,
            "unit_price_fen": ing.unit_price_fen,
        }

    use_db = await _check_db_mode(db)

    if use_db:
        # DB 模式：写入 stocktakes + stocktake_items 表
        await db.execute(
            text("""
                INSERT INTO stocktakes
                    (id, tenant_id, store_id, status, created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :store_id, 'open', :now, :now)
            """),
            {
                "id": stocktake_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "now": now,
            },
        )

        for item in items.values():
            await db.execute(
                text("""
                    INSERT INTO stocktake_items
                        (id, stocktake_id, tenant_id, ingredient_id,
                         ingredient_name, category, unit,
                         system_qty, actual_qty, unit_price_fen,
                         created_at, updated_at)
                    VALUES
                        (:id, :stocktake_id, :tenant_id, :ingredient_id,
                         :ingredient_name, :category, :unit,
                         :system_qty, NULL, :unit_price_fen,
                         :now, :now)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "stocktake_id": stocktake_id,
                    "tenant_id": tenant_id,
                    "ingredient_id": item["ingredient_id"],
                    "ingredient_name": item["ingredient_name"],
                    "category": item["category"],
                    "unit": item["unit"],
                    "system_qty": item["system_qty"],
                    "unit_price_fen": item["unit_price_fen"],
                    "now": now,
                },
            )

        await db.flush()
    else:
        # 内存降级模式
        _stocktakes[stocktake_id] = {
            "stocktake_id": stocktake_id,
            "store_id": store_id,
            "tenant_id": tenant_id,
            "status": "open",
            "created_at": now_iso,
            "items": items,
        }

    log.info("stocktake.created", stocktake_id=stocktake_id, item_count=len(items), mode="db" if use_db else "memory")

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
    use_db = await _check_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        # 查 stocktake 头（校验租户 + 状态）
        row = await db.execute(
            text("""
                SELECT id, tenant_id, status
                FROM stocktakes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": stocktake_id, "tenant_id": tenant_id},
        )
        stocktake_row = row.mappings().one_or_none()
        if not stocktake_row:
            return {"ok": False, "error": f"Stocktake {stocktake_id} not found"}
        if stocktake_row["status"] != "open":
            return {"ok": False, "error": f"Stocktake is {stocktake_row['status']}, not open"}

        # 查 item 行
        item_row = await db.execute(
            text("""
                SELECT id, ingredient_name, system_qty, unit_price_fen
                FROM stocktake_items
                WHERE stocktake_id = :stocktake_id
                  AND ingredient_id = :ingredient_id
                  AND tenant_id = :tenant_id
            """),
            {
                "stocktake_id": stocktake_id,
                "ingredient_id": ingredient_id,
                "tenant_id": tenant_id,
            },
        )
        item = item_row.mappings().one_or_none()
        if not item:
            return {"ok": False, "error": f"Ingredient {ingredient_id} not in stocktake"}

        system_qty = float(item["system_qty"])
        variance = actual_qty - system_qty

        # UPSERT actual_qty
        await db.execute(
            text("""
                UPDATE stocktake_items
                SET actual_qty = :actual_qty, updated_at = :now
                WHERE stocktake_id = :stocktake_id
                  AND ingredient_id = :ingredient_id
                  AND tenant_id = :tenant_id
            """),
            {
                "actual_qty": actual_qty,
                "now": datetime.now(timezone.utc),
                "stocktake_id": stocktake_id,
                "ingredient_id": ingredient_id,
                "tenant_id": tenant_id,
            },
        )
        await db.flush()

        log.info(
            "stocktake.count_recorded",
            stocktake_id=stocktake_id,
            ingredient_name=item["ingredient_name"],
            system_qty=system_qty,
            actual_qty=actual_qty,
            variance=variance,
        )

        return {
            "ok": True,
            "ingredient_id": ingredient_id,
            "ingredient_name": item["ingredient_name"],
            "system_qty": system_qty,
            "actual_qty": actual_qty,
            "variance": round(variance, 4),
        }

    # 内存降级模式
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
    use_db = await _check_db_mode(db)
    tenant_uuid = uuid.UUID(tenant_id)
    await _set_tenant(db, tenant_id)

    if use_db:
        # 查盘点头
        header_row = await db.execute(
            text("""
                SELECT id, store_id, status
                FROM stocktakes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": stocktake_id, "tenant_id": tenant_id},
        )
        header = header_row.mappings().one_or_none()
        if not header:
            return {"ok": False, "error": f"Stocktake {stocktake_id} not found"}
        if header["status"] != "open":
            return {"ok": False, "error": f"Stocktake already {header['status']}"}

        # 查所有明细行
        items_result = await db.execute(
            text("""
                SELECT ingredient_id, ingredient_name, unit,
                       system_qty, actual_qty, unit_price_fen
                FROM stocktake_items
                WHERE stocktake_id = :stocktake_id AND tenant_id = :tenant_id
            """),
            {"stocktake_id": stocktake_id, "tenant_id": tenant_id},
        )
        items_rows = items_result.mappings().all()
        store_id = str(header["store_id"])

    else:
        # 内存降级模式读取数据
        stocktake = _stocktakes.get(stocktake_id)
        if not stocktake:
            return {"ok": False, "error": f"Stocktake {stocktake_id} not found"}
        if stocktake["tenant_id"] != tenant_id:
            return {"ok": False, "error": "Tenant mismatch"}
        if stocktake["status"] != "open":
            return {"ok": False, "error": f"Stocktake already {stocktake['status']}"}

        store_id = stocktake["store_id"]
        items_rows = [
            {
                "ingredient_id": ing_id,
                "ingredient_name": v["ingredient_name"],
                "unit": v["unit"],
                "system_qty": v["system_qty"],
                "actual_qty": v.get("actual_qty"),
                "unit_price_fen": v.get("unit_price_fen") or 0,
            }
            for ing_id, v in stocktake["items"].items()
        ]

    total_items = len(items_rows)
    matched = surplus = deficit = uncounted = 0
    deficit_cost_fen = surplus_cost_fen = 0
    details: list[dict[str, Any]] = []

    async with db.begin_nested():
        for item in items_rows:
            actual_qty = item["actual_qty"]

            if actual_qty is None:
                uncounted += 1
                continue

            system_qty = float(item["system_qty"])
            actual_qty = float(actual_qty)
            variance = round(actual_qty - system_qty, 4)
            unit_price = int(item.get("unit_price_fen") or 0)

            if abs(variance) < 0.001:
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

            # 库存调整（仅差异 != 0 时）
            if abs(variance) >= 0.001:
                ing_uuid = uuid.UUID(str(item["ingredient_id"]))
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
                        store_id=uuid.UUID(store_id),
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
                "ingredient_id": str(item["ingredient_id"]),
                "ingredient_name": item["ingredient_name"],
                "unit": item["unit"],
                "system_qty": system_qty,
                "actual_qty": actual_qty,
                "variance": variance,
                "variance_cost_fen": int(abs(variance) * unit_price),
                "status": status,
            })

    now_finalized = datetime.now(timezone.utc)

    if use_db:
        await db.execute(
            text("""
                UPDATE stocktakes
                SET status = 'finalized',
                    finalized_at = :now,
                    updated_at = :now,
                    matched_count = :matched,
                    surplus_count = :surplus,
                    deficit_count = :deficit,
                    uncounted_count = :uncounted,
                    deficit_cost_fen = :deficit_cost_fen,
                    surplus_cost_fen = :surplus_cost_fen
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": stocktake_id,
                "tenant_id": tenant_id,
                "now": now_finalized,
                "matched": matched,
                "surplus": surplus,
                "deficit": deficit,
                "uncounted": uncounted,
                "deficit_cost_fen": deficit_cost_fen,
                "surplus_cost_fen": surplus_cost_fen,
            },
        )
    else:
        _stocktakes[stocktake_id]["status"] = "finalized"
        _stocktakes[stocktake_id]["finalized_at"] = now_finalized.isoformat()

    await db.flush()

    counted = total_items - uncounted

    log.info(
        "stocktake.finalized",
        stocktake_id=stocktake_id,
        total=total_items,
        matched=matched,
        surplus=surplus,
        deficit=deficit,
        deficit_cost_fen=deficit_cost_fen,
        mode="db" if use_db else "memory",
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
    use_db = await _check_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT
                    s.id AS stocktake_id,
                    s.store_id,
                    s.status,
                    s.created_at,
                    s.finalized_at,
                    COUNT(si.id) AS item_count
                FROM stocktakes s
                LEFT JOIN stocktake_items si
                    ON si.stocktake_id = s.id AND si.tenant_id = s.tenant_id
                WHERE s.store_id = :store_id AND s.tenant_id = :tenant_id
                GROUP BY s.id, s.store_id, s.status, s.created_at, s.finalized_at
                ORDER BY s.created_at DESC
            """),
            {"store_id": store_id, "tenant_id": tenant_id},
        )
        rows = result.mappings().all()
        records = [
            {
                "stocktake_id": str(r["stocktake_id"]),
                "store_id": str(r["store_id"]),
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                "finalized_at": r["finalized_at"].isoformat() if r["finalized_at"] and hasattr(r["finalized_at"], "isoformat") else r["finalized_at"],
                "item_count": r["item_count"],
            }
            for r in rows
        ]
    else:
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
        records.sort(key=lambda x: x["created_at"], reverse=True)

    return {"ok": True, "stocktakes": records}
