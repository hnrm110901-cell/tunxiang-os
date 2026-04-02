"""供应链移动端 Service"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class ReceivingOrderNotFoundError(Exception):
    pass


class StocktakeSessionNotFoundError(Exception):
    pass


class StocktakeAlreadyCompletedError(Exception):
    pass


class PurchaseOrderNotFoundError(Exception):
    pass


async def create_receiving_order(
    store_id: str,
    supplier_name: str,
    items: list[dict],
    tenant_id: str,
    db: AsyncSession,
    receiver_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    order_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(text("""
        INSERT INTO receiving_orders
            (id, tenant_id, store_id, supplier_name, status, receiver_id, notes, photo_urls, created_at)
        VALUES
            (:id, :tenant_id, :store_id, :supplier_name, 'draft', :receiver_id, :notes, '[]', :now)
    """), {
        "id": order_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "supplier_name": supplier_name,
        "receiver_id": receiver_id,
        "notes": notes,
        "now": now,
    })

    for item in items:
        await db.execute(text("""
            INSERT INTO receiving_items
                (id, tenant_id, receiving_order_id, ingredient_id, ingredient_name,
                 unit, ordered_qty, received_qty, unit_price, created_at)
            VALUES
                (:id, :tenant_id, :order_id, :ingredient_id, :ingredient_name,
                 :unit, :ordered_qty, :received_qty, :unit_price, :now)
        """), {
            "id": str(uuid4()),
            "tenant_id": tenant_id,
            "order_id": order_id,
            "ingredient_id": item.get("ingredient_id"),
            "ingredient_name": item["ingredient_name"],
            "unit": item.get("unit"),
            "ordered_qty": item.get("ordered_qty"),
            "received_qty": item.get("received_qty"),
            "unit_price": item.get("unit_price"),
            "now": now,
        })

    await db.commit()
    log.info("receiving_order_created", order_id=order_id, store_id=store_id, tenant_id=tenant_id)
    return {"order_id": order_id}


async def confirm_receiving(
    order_id: str,
    received_items: list[dict],
    tenant_id: str,
    db: AsyncSession,
    photo_urls: Optional[list[str]] = None,
) -> dict:
    row = await db.execute(text("""
        SELECT id, status FROM receiving_orders
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """), {"id": order_id, "tenant_id": tenant_id})
    order = row.fetchone()
    if not order:
        raise ReceivingOrderNotFoundError(f"receiving order {order_id} not found")

    has_discrepancy = False
    for item in received_items:
        ordered = item.get("ordered_qty")
        received = item.get("received_qty")
        if ordered is not None and received is not None:
            if Decimal(str(received)) != Decimal(str(ordered)):
                has_discrepancy = True

        await db.execute(text("""
            UPDATE receiving_items
            SET received_qty = :received_qty,
                discrepancy_note = :note
            WHERE receiving_order_id = :order_id
              AND ingredient_name = :ingredient_name
              AND tenant_id = :tenant_id
        """), {
            "received_qty": item.get("received_qty"),
            "note": item.get("discrepancy_note"),
            "order_id": order_id,
            "ingredient_name": item["ingredient_name"],
            "tenant_id": tenant_id,
        })

    new_status = "discrepancy" if has_discrepancy else "confirmed"
    import json
    await db.execute(text("""
        UPDATE receiving_orders
        SET status = :status,
            received_at = :now,
            photo_urls = :photos
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "status": new_status,
        "now": datetime.now(timezone.utc),
        "photos": json.dumps(photo_urls or []),
        "id": order_id,
        "tenant_id": tenant_id,
    })

    await db.commit()
    log.info("receiving_order_confirmed", order_id=order_id, status=new_status, tenant_id=tenant_id)
    return {"order_id": order_id, "status": new_status, "has_discrepancy": has_discrepancy}


async def get_receiving_history(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    days: int = 7,
) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.execute(text("""
        SELECT o.id, o.supplier_name, o.status, o.received_at, o.created_at,
               COUNT(i.id) AS item_count,
               SUM(i.received_qty * COALESCE(i.unit_price, 0)) AS total_amount
        FROM receiving_orders o
        LEFT JOIN receiving_items i ON i.receiving_order_id = o.id AND i.tenant_id = o.tenant_id
        WHERE o.store_id = :store_id
          AND o.tenant_id = :tenant_id
          AND o.is_deleted = FALSE
          AND o.created_at >= :since
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 100
    """), {"store_id": store_id, "tenant_id": tenant_id, "since": since})

    return [
        {
            "id": str(r.id),
            "supplier_name": r.supplier_name,
            "status": r.status,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "created_at": r.created_at.isoformat(),
            "item_count": r.item_count,
            "total_amount": float(r.total_amount) if r.total_amount else 0,
        }
        for r in rows.fetchall()
    ]


async def start_stocktake(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    category: Optional[str] = None,
    initiated_by: Optional[str] = None,
) -> dict:
    session_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(text("""
        INSERT INTO stocktake_sessions
            (id, tenant_id, store_id, category, status, initiated_by, created_at)
        VALUES
            (:id, :tenant_id, :store_id, :category, 'in_progress', :initiated_by, :now)
    """), {
        "id": session_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "category": category,
        "initiated_by": initiated_by,
        "now": now,
    })

    await db.commit()
    log.info("stocktake_started", session_id=session_id, store_id=store_id, tenant_id=tenant_id)
    return {"session_id": session_id}


async def record_count(
    session_id: str,
    ingredient_name: str,
    actual_qty: Decimal,
    tenant_id: str,
    db: AsyncSession,
    ingredient_id: Optional[str] = None,
    unit: Optional[str] = None,
    counted_by: Optional[str] = None,
    system_qty: Optional[Decimal] = None,
    unit_cost: Optional[Decimal] = None,
) -> dict:
    row = await db.execute(text("""
        SELECT id, status FROM stocktake_sessions
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """), {"id": session_id, "tenant_id": tenant_id})
    session = row.fetchone()
    if not session:
        raise StocktakeSessionNotFoundError(f"stocktake session {session_id} not found")
    if session.status == "completed":
        raise StocktakeAlreadyCompletedError(f"session {session_id} already completed")

    variance = None
    variance_value = None
    if system_qty is not None:
        variance = actual_qty - system_qty
        if unit_cost is not None:
            variance_value = variance * unit_cost

    existing = await db.execute(text("""
        SELECT id FROM stocktake_items
        WHERE session_id = :session_id AND ingredient_name = :name AND tenant_id = :tenant_id
    """), {"session_id": session_id, "name": ingredient_name, "tenant_id": tenant_id})
    existing_row = existing.fetchone()
    now = datetime.now(timezone.utc)

    if existing_row:
        await db.execute(text("""
            UPDATE stocktake_items
            SET actual_qty = :actual_qty,
                variance = :variance,
                variance_value = :variance_value,
                counted_by = :counted_by,
                counted_at = :now
            WHERE id = :id AND tenant_id = :tenant_id
        """), {
            "actual_qty": actual_qty,
            "variance": variance,
            "variance_value": variance_value,
            "counted_by": counted_by,
            "now": now,
            "id": str(existing_row.id),
            "tenant_id": tenant_id,
        })
        item_id = str(existing_row.id)
    else:
        item_id = str(uuid4())
        await db.execute(text("""
            INSERT INTO stocktake_items
                (id, tenant_id, session_id, ingredient_id, ingredient_name, unit,
                 system_qty, actual_qty, variance, variance_value, counted_by, counted_at, created_at)
            VALUES
                (:id, :tenant_id, :session_id, :ingredient_id, :ingredient_name, :unit,
                 :system_qty, :actual_qty, :variance, :variance_value, :counted_by, :now, :now)
        """), {
            "id": item_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient_name,
            "unit": unit,
            "system_qty": system_qty,
            "actual_qty": actual_qty,
            "variance": variance,
            "variance_value": variance_value,
            "counted_by": counted_by,
            "now": now,
        })

    await db.commit()
    return {
        "item_id": item_id,
        "ingredient_name": ingredient_name,
        "actual_qty": float(actual_qty),
        "variance": float(variance) if variance is not None else None,
        "variance_value": float(variance_value) if variance_value is not None else None,
    }


async def complete_stocktake(
    session_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    row = await db.execute(text("""
        SELECT id, status FROM stocktake_sessions
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """), {"id": session_id, "tenant_id": tenant_id})
    session = row.fetchone()
    if not session:
        raise StocktakeSessionNotFoundError(f"stocktake session {session_id} not found")
    if session.status == "completed":
        raise StocktakeAlreadyCompletedError(f"session {session_id} already completed")

    await db.execute(text("""
        UPDATE stocktake_sessions
        SET status = 'completed', completed_at = :now
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"now": datetime.now(timezone.utc), "id": session_id, "tenant_id": tenant_id})

    await db.commit()

    report = await get_stocktake_report(session_id, tenant_id, db)
    log.info("stocktake_completed", session_id=session_id, tenant_id=tenant_id)
    return report


async def get_stocktake_report(
    session_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    items_rows = await db.execute(text("""
        SELECT ingredient_name, unit, system_qty, actual_qty, variance, variance_value, counted_at
        FROM stocktake_items
        WHERE session_id = :session_id AND tenant_id = :tenant_id
        ORDER BY ingredient_name
    """), {"session_id": session_id, "tenant_id": tenant_id})

    items = items_rows.fetchall()
    surplus_items = [i for i in items if i.variance is not None and i.variance > 0]
    shortage_items = [i for i in items if i.variance is not None and i.variance < 0]
    total_variance_value = sum(
        float(i.variance_value) for i in items if i.variance_value is not None
    )

    return {
        "session_id": session_id,
        "total_items": len(items),
        "counted_items": sum(1 for i in items if i.actual_qty is not None),
        "surplus_count": len(surplus_items),
        "shortage_count": len(shortage_items),
        "total_variance_value": total_variance_value,
        "items": [
            {
                "ingredient_name": i.ingredient_name,
                "unit": i.unit,
                "system_qty": float(i.system_qty) if i.system_qty is not None else None,
                "actual_qty": float(i.actual_qty) if i.actual_qty is not None else None,
                "variance": float(i.variance) if i.variance is not None else None,
                "variance_value": float(i.variance_value) if i.variance_value is not None else None,
                "counted_at": i.counted_at.isoformat() if i.counted_at else None,
            }
            for i in items
        ],
    }


async def get_pending_approvals(
    approver_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    rows = await db.execute(text("""
        SELECT id, requester_name, items_summary, estimated_amount, created_at, notes
        FROM purchase_orders
        WHERE store_id = :store_id
          AND tenant_id = :tenant_id
          AND status = 'pending_approval'
          AND is_deleted = FALSE
        ORDER BY created_at ASC
        LIMIT 50
    """), {"store_id": store_id, "tenant_id": tenant_id})

    result = []
    for r in rows.fetchall():
        result.append({
            "id": str(r.id),
            "requester_name": r.requester_name,
            "items_summary": r.items_summary,
            "estimated_amount": float(r.estimated_amount) if r.estimated_amount else 0,
            "created_at": r.created_at.isoformat(),
            "notes": r.notes,
        })
    return result


async def approve_purchase(
    purchase_id: str,
    approved: bool,
    approver_id: str,
    tenant_id: str,
    db: AsyncSession,
    comment: Optional[str] = None,
) -> dict:
    row = await db.execute(text("""
        SELECT id, status FROM purchase_orders
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """), {"id": purchase_id, "tenant_id": tenant_id})
    order = row.fetchone()
    if not order:
        raise PurchaseOrderNotFoundError(f"purchase order {purchase_id} not found")

    new_status = "approved" if approved else "rejected"
    await db.execute(text("""
        UPDATE purchase_orders
        SET status = :status,
            approver_id = :approver_id,
            approval_comment = :comment,
            approved_at = :now
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "status": new_status,
        "approver_id": approver_id,
        "comment": comment,
        "now": datetime.now(timezone.utc),
        "id": purchase_id,
        "tenant_id": tenant_id,
    })

    await db.commit()
    log.info("purchase_order_approved", purchase_id=purchase_id, approved=approved, tenant_id=tenant_id)
    return {"purchase_id": purchase_id, "status": new_status}
