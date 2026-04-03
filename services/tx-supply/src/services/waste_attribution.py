"""损耗归因分析 -- 从 waste_events 表提取多维度损耗报告

维度：
- by_type: 按损耗类型 (expired/spoiled/overproduction/damage/...)
- by_ingredient: 按食材排行（金额+次数）
- by_time_slot: 按时段分布

金额单位：分(fen)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import Date, cast, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction

log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  损耗归因分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def analyze_waste(
    store_id: str,
    date_from: str,
    date_to: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """多维度损耗归因分析

    从 ingredient_transactions (type=waste) 汇总：
    - by_type: 按损耗原因分类（从 notes 字段解析或 waste_events 关联）
    - by_ingredient: 按食材维度金额排行
    - by_time_slot: 按小时段分布
    - total_waste_cost_fen / waste_rate_pct

    Args:
        store_id: 门店 UUID
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        tenant_id: 租户 UUID
        db: 数据库会话

    Returns:
        完整损耗分析报告
    """
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    await _set_tenant(db, tenant_id)

    # ─── 按食材汇总 ───
    by_ingredient_query = (
        select(
            Ingredient.id.label("ing_id"),
            Ingredient.ingredient_name,
            Ingredient.category,
            Ingredient.unit,
            Ingredient.unit_price_fen,
            func.count(IngredientTransaction.id).label("event_count"),
            func.sum(func.abs(IngredientTransaction.quantity)).label("total_qty"),
        )
        .join(IngredientTransaction, IngredientTransaction.ingredient_id == Ingredient.id)
        .where(Ingredient.tenant_id == tenant_uuid)
        .where(Ingredient.store_id == store_uuid)
        .where(IngredientTransaction.transaction_type == "waste")
        .where(IngredientTransaction.is_deleted == False)  # noqa: E712
        .where(cast(IngredientTransaction.created_at, Date) >= date_from)
        .where(cast(IngredientTransaction.created_at, Date) <= date_to)
        .group_by(
            Ingredient.id,
            Ingredient.ingredient_name,
            Ingredient.category,
            Ingredient.unit,
            Ingredient.unit_price_fen,
        )
        .order_by(desc("total_qty"))
    )

    result = await db.execute(by_ingredient_query)
    rows = result.all()

    by_ingredient: list[dict[str, Any]] = []
    total_waste_cost_fen = 0
    total_waste_qty = 0.0

    for row in rows:
        ing_name = row.ingredient_name
        unit_price = row.unit_price_fen or 0
        total_qty = float(row.total_qty) if row.total_qty else 0.0
        cost_fen = int(total_qty * unit_price)
        total_waste_cost_fen += cost_fen
        total_waste_qty += total_qty

        by_ingredient.append({
            "ingredient_id": str(row.ing_id),
            "name": ing_name,
            "category": row.category,
            "unit": row.unit,
            "total_qty": round(total_qty, 4),
            "total_cost_fen": cost_fen,
            "total_cost_yuan": round(cost_fen / 100, 2),
            "count": row.event_count,
        })

    # ─── 按时段汇总（小时段） ───
    hour_query = (
        select(
            func.extract("hour", IngredientTransaction.created_at).label("hour"),
            func.count(IngredientTransaction.id).label("event_count"),
            func.sum(func.abs(IngredientTransaction.quantity)).label("total_qty"),
        )
        .where(IngredientTransaction.tenant_id == tenant_uuid)
        .where(IngredientTransaction.store_id == store_uuid)
        .where(IngredientTransaction.transaction_type == "waste")
        .where(IngredientTransaction.is_deleted == False)  # noqa: E712
        .where(cast(IngredientTransaction.created_at, Date) >= date_from)
        .where(cast(IngredientTransaction.created_at, Date) <= date_to)
        .group_by("hour")
        .order_by("hour")
    )

    hour_result = await db.execute(hour_query)
    hour_rows = hour_result.all()

    by_time_slot: list[dict[str, Any]] = []
    for row in hour_rows:
        hour = int(row.hour) if row.hour is not None else 0
        qty = float(row.total_qty) if row.total_qty else 0.0
        by_time_slot.append({
            "hour": hour,
            "time_range": f"{hour:02d}:00-{hour:02d}:59",
            "event_count": row.event_count,
            "total_qty": round(qty, 4),
        })

    # ─── 按损耗类型汇总 ───
    # 从 notes 字段解析或使用 waste_events 表
    # MVP: 从 waste_events 表直接查询
    by_type: dict[str, dict[str, Any]] = {}
    try:
        type_query = text("""
            SELECT
                event_type,
                COUNT(*) AS event_count,
                SUM(CAST(quantity AS FLOAT)) AS total_qty
            FROM waste_events
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND is_deleted = false
              AND CAST(occurred_at AS DATE) >= CAST(:date_from AS DATE)
              AND CAST(occurred_at AS DATE) <= CAST(:date_to AS DATE)
            GROUP BY event_type
            ORDER BY total_qty DESC
        """)
        type_result = await db.execute(type_query, {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": date_from,
            "date_to": date_to,
        })
        type_rows = type_result.all()
        for row in type_rows:
            event_type = row[0]
            count = row[1]
            qty = float(row[2]) if row[2] else 0.0
            by_type[event_type] = {
                "type": event_type,
                "event_count": count,
                "total_qty": round(qty, 4),
            }
    except (OSError, ValueError, RuntimeError) as exc:
        log.warning("waste_events_query_failed", store_id=store_id, error=str(exc))
        # 降级：无类型分布数据
        by_type = {}

    # ─── 损耗率（需要营收数据，此处暂返回 None） ───
    waste_rate_pct: Optional[float] = None

    log.info(
        "waste_analysis.done",
        store_id=store_id,
        total_cost_fen=total_waste_cost_fen,
        ingredient_count=len(by_ingredient),
    )

    return {
        "ok": True,
        "store_id": store_id,
        "period": {"from": date_from, "to": date_to},
        "total_waste_cost_fen": total_waste_cost_fen,
        "total_waste_cost_yuan": round(total_waste_cost_fen / 100, 2),
        "total_waste_qty": round(total_waste_qty, 4),
        "waste_rate_pct": waste_rate_pct,
        "by_type": by_type,
        "by_ingredient": by_ingredient,
        "by_time_slot": by_time_slot,
    }


# ─── 损耗金额 Top N ───


async def get_top_waste_items(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    limit: int = 10,
    days: int = 30,
) -> dict[str, Any]:
    """损耗金额最高的原料排行

    Args:
        store_id: 门店 UUID
        tenant_id: 租户 UUID
        db: 数据库会话
        limit: 返回条数
        days: 回看天数

    Returns:
        {ok, items: [{rank, name, total_cost_fen, total_qty, count}]}
    """
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    await _set_tenant(db, tenant_id)

    since = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    from datetime import timedelta
    since = since - timedelta(days=days)

    query = (
        select(
            Ingredient.ingredient_name,
            Ingredient.category,
            Ingredient.unit,
            Ingredient.unit_price_fen,
            func.count(IngredientTransaction.id).label("event_count"),
            func.sum(func.abs(IngredientTransaction.quantity)).label("total_qty"),
        )
        .join(IngredientTransaction, IngredientTransaction.ingredient_id == Ingredient.id)
        .where(Ingredient.tenant_id == tenant_uuid)
        .where(Ingredient.store_id == store_uuid)
        .where(IngredientTransaction.transaction_type == "waste")
        .where(IngredientTransaction.is_deleted == False)  # noqa: E712
        .where(IngredientTransaction.created_at >= since)
        .group_by(
            Ingredient.ingredient_name,
            Ingredient.category,
            Ingredient.unit,
            Ingredient.unit_price_fen,
        )
    )

    result = await db.execute(query)
    rows = result.all()

    # 计算成本并排序
    items_with_cost: list[dict[str, Any]] = []
    for row in rows:
        unit_price = row.unit_price_fen or 0
        total_qty = float(row.total_qty) if row.total_qty else 0.0
        cost_fen = int(total_qty * unit_price)
        items_with_cost.append({
            "name": row.ingredient_name,
            "category": row.category,
            "unit": row.unit,
            "total_qty": round(total_qty, 4),
            "total_cost_fen": cost_fen,
            "total_cost_yuan": round(cost_fen / 100, 2),
            "count": row.event_count,
        })

    items_with_cost.sort(key=lambda x: x["total_cost_fen"], reverse=True)
    top_items = items_with_cost[:limit]

    # 添加排名
    for i, item in enumerate(top_items, 1):
        item["rank"] = i

    return {
        "ok": True,
        "store_id": store_id,
        "period_days": days,
        "items": top_items,
    }
