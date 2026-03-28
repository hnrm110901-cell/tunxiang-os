"""安全库存与沽清预测服务

基于近 7 天平均消耗计算安全库存，预测沽清日期，生成采购建议。
安全天数默认 3 天。
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus, TransactionType

logger = structlog.get_logger()

DEFAULT_SAFETY_DAYS = 3
CONSUMPTION_LOOKBACK_DAYS = 7


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_daily_consumption(
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    lookback_days: int = CONSUMPTION_LOOKBACK_DAYS,
) -> float:
    """计算原料近 N 天的日均消耗量

    统计 usage 类型事务的总量 / 天数
    """
    tid = _uuid(tenant_id)
    iid = _uuid(ingredient_id)
    sid = _uuid(store_id)
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    q = (
        select(func.coalesce(func.sum(IngredientTransaction.quantity), 0))
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.ingredient_id == iid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type == TransactionType.usage.value,
            IngredientTransaction.is_deleted == False,  # noqa: E712
            IngredientTransaction.created_at >= since,
        )
    )
    result = await db.execute(q)
    total = float(result.scalar() or 0)
    return total / lookback_days


async def check_safety_stock(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    safety_days: int = DEFAULT_SAFETY_DAYS,
) -> list[dict]:
    """检查门店所有原料的安全库存状态

    安全库存 = 日均消耗 x 安全天数
    status:
        - "ok": 当前库存 >= 安全库存
        - "low": 当前库存 < 安全库存 且 > 安全库存 * 0.5
        - "critical": 当前库存 <= 安全库存 * 0.5

    Returns: [{ingredient_id, ingredient_name, current_qty, safety_qty,
               daily_consumption, status}]
    """
    await _set_tenant(db, tenant_id)
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)

    ing_q = (
        select(Ingredient)
        .where(
            Ingredient.tenant_id == tid,
            Ingredient.store_id == sid,
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(ing_q)
    ingredients = result.scalars().all()

    items = []
    for ing in ingredients:
        daily = await _get_daily_consumption(
            str(ing.id), store_id, tenant_id, db,
        )
        safety_qty = daily * safety_days

        # 也参考原料自身的 min_quantity 配置
        effective_safety = max(safety_qty, ing.min_quantity)

        if ing.current_quantity >= effective_safety:
            status = "ok"
        elif ing.current_quantity > effective_safety * 0.5:
            status = "low"
        else:
            status = "critical"

        items.append({
            "ingredient_id": str(ing.id),
            "ingredient_name": ing.ingredient_name,
            "category": ing.category,
            "unit": ing.unit,
            "current_qty": ing.current_quantity,
            "safety_qty": round(effective_safety, 2),
            "daily_consumption": round(daily, 2),
            "status": status,
        })

    # 优先展示 critical > low > ok
    priority = {"critical": 0, "low": 1, "ok": 2}
    items.sort(key=lambda x: priority.get(x["status"], 9))

    logger.info(
        "safety_stock_checked",
        store_id=store_id,
        total=len(items),
        critical=sum(1 for i in items if i["status"] == "critical"),
        low=sum(1 for i in items if i["status"] == "low"),
        tenant_id=tenant_id,
    )
    return items


async def predict_stockout(
    store_id: str,
    ingredient_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """预测单个原料的沽清日期

    Returns: {
        ingredient_id, ingredient_name,
        estimated_stockout_date, daily_consumption,
        current_qty, days_remaining
    }
    """
    await _set_tenant(db, tenant_id)

    ing_result = await db.execute(
        select(Ingredient).where(
            Ingredient.id == _uuid(ingredient_id),
            Ingredient.store_id == _uuid(store_id),
            Ingredient.tenant_id == _uuid(tenant_id),
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ingredient = ing_result.scalar_one_or_none()
    if ingredient is None:
        raise ValueError(f"原料 {ingredient_id} 在门店 {store_id} 不存在")

    daily = await _get_daily_consumption(
        ingredient_id, store_id, tenant_id, db,
    )

    today = date.today()
    if daily <= 0:
        return {
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient.ingredient_name,
            "estimated_stockout_date": None,
            "daily_consumption": 0,
            "current_qty": ingredient.current_quantity,
            "days_remaining": None,
            "message": "近期无消耗记录，无法预测",
        }

    days_remaining = ingredient.current_quantity / daily
    stockout_date = today + timedelta(days=int(days_remaining))

    logger.info(
        "stockout_predicted",
        ingredient_id=ingredient_id,
        days_remaining=round(days_remaining, 1),
        daily_consumption=round(daily, 2),
        store_id=store_id,
        tenant_id=tenant_id,
    )

    return {
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient.ingredient_name,
        "estimated_stockout_date": stockout_date.isoformat(),
        "daily_consumption": round(daily, 2),
        "current_qty": ingredient.current_quantity,
        "days_remaining": round(days_remaining, 1),
    }


async def suggest_reorder(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    safety_days: int = DEFAULT_SAFETY_DAYS,
    reorder_cycle_days: int = 3,
) -> list[dict]:
    """生成采购建议

    对于 low/critical 状态的原料，建议补货量 = 日均消耗 x (安全天数 + 采购周期) - 当前库存。
    urgency: "urgent" (critical) | "normal" (low)

    Returns: [{ingredient_id, ingredient_name, reorder_qty, urgency,
               estimated_cost_fen, daily_consumption, current_qty}]
    """
    safety_items = await check_safety_stock(store_id, tenant_id, db, safety_days)

    suggestions = []
    for item in safety_items:
        if item["status"] == "ok":
            continue

        daily = item["daily_consumption"]
        if daily <= 0:
            # 无消耗但库存低于 min_quantity，按 min_quantity 补货
            reorder_qty = item["safety_qty"] - item["current_qty"]
        else:
            target = daily * (safety_days + reorder_cycle_days)
            reorder_qty = max(target - item["current_qty"], 0)

        if reorder_qty <= 0:
            continue

        # 获取最近单价估算成本
        ing_result = await db.execute(
            select(Ingredient).where(
                Ingredient.id == _uuid(item["ingredient_id"]),
                Ingredient.tenant_id == _uuid(tenant_id),
                Ingredient.is_deleted == False,  # noqa: E712
            )
        )
        ingredient = ing_result.scalar_one_or_none()
        unit_price = (ingredient.unit_price_fen or 0) if ingredient else 0
        estimated_cost = round(unit_price * reorder_qty)

        urgency = "urgent" if item["status"] == "critical" else "normal"

        suggestions.append({
            "ingredient_id": item["ingredient_id"],
            "ingredient_name": item["ingredient_name"],
            "category": item["category"],
            "unit": item["unit"],
            "reorder_qty": round(reorder_qty, 2),
            "urgency": urgency,
            "estimated_cost_fen": estimated_cost,
            "daily_consumption": daily,
            "current_qty": item["current_qty"],
            "safety_qty": item["safety_qty"],
        })

    # urgent 排前面
    suggestions.sort(key=lambda x: 0 if x["urgency"] == "urgent" else 1)

    logger.info(
        "reorder_suggested",
        store_id=store_id,
        total_suggestions=len(suggestions),
        urgent=sum(1 for s in suggestions if s["urgency"] == "urgent"),
        tenant_id=tenant_id,
    )
    return suggestions
