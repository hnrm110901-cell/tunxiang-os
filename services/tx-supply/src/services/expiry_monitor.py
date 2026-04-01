"""效期监控服务 -- 食安合规：临期/过期原料预警

三条硬约束之一：食安合规 — 临期/过期食材不可用于出品。
过期原料 = food safety violation，必须处理。
"""
import asyncio
import json
import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher, SupplyEventType
from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import TransactionType

logger = structlog.get_logger()


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    from sqlalchemy import text
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _parse_notes_expiry(notes: Optional[str]) -> Optional[date]:
    """从 transaction notes JSON 解析 expiry_date"""
    if not notes:
        return None
    try:
        data = json.loads(notes)
        expiry_str = data.get("expiry_date")
        return date.fromisoformat(expiry_str) if expiry_str else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def _get_active_batches(
    store_id: str, tenant_id: str, db: AsyncSession,
) -> list[dict]:
    """获取门店所有有剩余库存的批次

    Returns: [{ingredient_id, ingredient_name, batch_no, expiry_date,
               remaining, unit_cost_fen, created_at}]
    """
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)

    # 获取门店所有原料
    ing_q = (
        select(Ingredient)
        .where(
            Ingredient.tenant_id == tid,
            Ingredient.store_id == sid,
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ing_result = await db.execute(ing_q)
    ingredients = {str(i.id): i for i in ing_result.scalars().all()}

    if not ingredients:
        return []

    ingredient_ids = [_uuid(iid) for iid in ingredients]

    # 获取所有 purchase 事务（批次来源）
    purchase_q = (
        select(IngredientTransaction)
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type == TransactionType.purchase.value,
            IngredientTransaction.ingredient_id.in_(ingredient_ids),
            IngredientTransaction.is_deleted == False,  # noqa: E712
        )
        .order_by(IngredientTransaction.created_at.asc())
    )
    purchase_result = await db.execute(purchase_q)
    purchases = purchase_result.scalars().all()

    # 获取所有出库事务汇总（按 ingredient_id + batch_no 分组）
    out_types = [
        TransactionType.usage.value,
        TransactionType.waste.value,
        TransactionType.transfer.value,
    ]
    out_q = (
        select(
            IngredientTransaction.ingredient_id,
            IngredientTransaction.reference_id,
            func.sum(IngredientTransaction.quantity).label("out_total"),
        )
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type.in_(out_types),
            IngredientTransaction.ingredient_id.in_(ingredient_ids),
            IngredientTransaction.is_deleted == False,  # noqa: E712
        )
        .group_by(
            IngredientTransaction.ingredient_id,
            IngredientTransaction.reference_id,
        )
    )
    out_result = await db.execute(out_q)
    out_map: dict[str, float] = {}
    for row in out_result.all():
        key = f"{row.ingredient_id}|{row.reference_id or ''}"
        out_map[key] = float(row.out_total)

    batches = []
    for p in purchases:
        batch_no = p.reference_id or ""
        key = f"{p.ingredient_id}|{batch_no}"
        used = out_map.get(key, 0.0)
        remaining = float(p.quantity) - used
        if remaining <= 0.001:
            continue

        expiry = _parse_notes_expiry(p.notes)
        ing = ingredients.get(str(p.ingredient_id))
        if not ing:
            continue

        batches.append({
            "ingredient_id": str(p.ingredient_id),
            "ingredient_name": ing.ingredient_name,
            "category": ing.category,
            "unit": ing.unit,
            "batch_no": batch_no,
            "expiry_date": expiry,
            "remaining": remaining,
            "unit_cost_fen": p.unit_cost_fen,
            "created_at": p.created_at,
        })

    return batches


async def check_expiring_items(
    store_id: str,
    days_ahead: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询即将到期的原料批次

    Args:
        days_ahead: 提前几天预警（如 3 表示 3 天内到期）

    Returns: [{ingredient_name, batch_no, expiry_date, remaining_days, quantity, cost_fen}]
    """
    await _set_tenant(db, tenant_id)
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    batches = await _get_active_batches(store_id, tenant_id, db)
    expiring = []

    for b in batches:
        exp = b["expiry_date"]
        if exp is None:
            continue
        if today <= exp <= cutoff:
            remaining_days = (exp - today).days
            cost = round((b["unit_cost_fen"] or 0) * b["remaining"])
            expiring.append({
                "ingredient_id": b["ingredient_id"],
                "ingredient_name": b["ingredient_name"],
                "category": b["category"],
                "batch_no": b["batch_no"],
                "expiry_date": exp.isoformat(),
                "remaining_days": remaining_days,
                "quantity": b["remaining"],
                "unit": b["unit"],
                "cost_fen": cost,
            })

    expiring.sort(key=lambda x: x["remaining_days"])

    logger.info(
        "expiring_items_checked",
        store_id=store_id,
        days_ahead=days_ahead,
        count=len(expiring),
        tenant_id=tenant_id,
    )

    # ── 事件总线：食材临期预警 ──────────────────────────────
    for item in expiring:
        asyncio.create_task(UniversalPublisher.publish(
            event_type=SupplyEventType.INGREDIENT_EXPIRING,
            tenant_id=_uuid(tenant_id),
            store_id=_uuid(store_id),
            entity_id=_uuid(item["ingredient_id"]),
            event_data={
                "ingredient_id": item["ingredient_id"],
                "expire_date": item["expiry_date"],
                "days_remaining": item["remaining_days"],
                "qty": item["quantity"],
            },
            source_service="tx-supply",
        ))

    return expiring


async def check_expired_items(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询已过期但库存>0的原料（食安合规：必须处理）

    Returns: [{ingredient_name, batch_no, expiry_date, days_overdue, quantity, cost_fen}]
    """
    await _set_tenant(db, tenant_id)
    today = date.today()

    batches = await _get_active_batches(store_id, tenant_id, db)
    expired = []

    for b in batches:
        exp = b["expiry_date"]
        if exp is None:
            continue
        if exp < today:
            days_overdue = (today - exp).days
            cost = round((b["unit_cost_fen"] or 0) * b["remaining"])
            expired.append({
                "ingredient_id": b["ingredient_id"],
                "ingredient_name": b["ingredient_name"],
                "category": b["category"],
                "batch_no": b["batch_no"],
                "expiry_date": exp.isoformat(),
                "days_overdue": days_overdue,
                "quantity": b["remaining"],
                "unit": b["unit"],
                "cost_fen": cost,
            })

    expired.sort(key=lambda x: x["days_overdue"], reverse=True)

    if expired:
        logger.warning(
            "expired_items_found",
            store_id=store_id,
            count=len(expired),
            total_cost_fen=sum(e["cost_fen"] for e in expired),
            tenant_id=tenant_id,
        )
    return expired


async def generate_expiry_report(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """生成效期综合报告

    Returns: {
        expired_count, expired_cost_fen,
        expiring_3d_count, expiring_3d_cost_fen,
        expiring_7d_count, expiring_7d_cost_fen,
        total_risk_cost_fen,
        details: {expired: [...], expiring_3d: [...], expiring_7d: [...]}
    }
    """
    expired = await check_expired_items(store_id, tenant_id, db)
    expiring_3d = await check_expiring_items(store_id, 3, tenant_id, db)
    expiring_7d = await check_expiring_items(store_id, 7, tenant_id, db)

    expired_cost = sum(e["cost_fen"] for e in expired)
    cost_3d = sum(e["cost_fen"] for e in expiring_3d)
    cost_7d = sum(e["cost_fen"] for e in expiring_7d)

    report = {
        "expired_count": len(expired),
        "expired_cost_fen": expired_cost,
        "expiring_3d_count": len(expiring_3d),
        "expiring_3d_cost_fen": cost_3d,
        "expiring_7d_count": len(expiring_7d),
        "expiring_7d_cost_fen": cost_7d,
        "total_risk_cost_fen": expired_cost + cost_7d,
        "details": {
            "expired": expired,
            "expiring_3d": expiring_3d,
            "expiring_7d": expiring_7d,
        },
    }

    logger.info(
        "expiry_report_generated",
        store_id=store_id,
        expired_count=len(expired),
        expiring_3d=len(expiring_3d),
        expiring_7d=len(expiring_7d),
        total_risk_cost_fen=report["total_risk_cost_fen"],
        tenant_id=tenant_id,
    )
    return report
