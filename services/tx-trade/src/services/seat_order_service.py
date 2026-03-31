"""座位点单 Service"""
import math
import secrets
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─── Pydantic 模型 ───

class OrderSeat(BaseModel):
    id: UUID
    tenant_id: UUID
    order_id: UUID
    seat_no: int
    seat_label: str
    sub_total: Decimal
    paid_amount: Decimal
    payment_status: str


class SeatItem(BaseModel):
    item_id: str
    name: str
    qty: int
    price: Decimal
    seat_no: Optional[int]
    share_count: Optional[int] = None
    share_amount: Optional[Decimal] = None


class SeatSummary(BaseModel):
    seat_no: int
    seat_label: str
    items: list[SeatItem]
    sub_total: Decimal
    paid_amount: Decimal
    payment_status: str


class SplitBill(BaseModel):
    group_label: str
    seat_nos: list[int]
    items: list[SeatItem]
    total_amount: Decimal


# ─── 函数 ───

async def init_seats(
    order_id: UUID,
    seat_count: int,
    tenant_id: UUID,
    db: AsyncSession,
) -> list[OrderSeat]:
    if not (1 <= seat_count <= 20):
        raise ValueError(f"seat_count 必须在 1-20 之间，得到: {seat_count}")

    await db.execute(
        text("UPDATE orders SET seat_count = :sc WHERE id = :oid AND tenant_id = :tid"),
        {"sc": seat_count, "oid": str(order_id), "tid": str(tenant_id)},
    )

    rows = []
    for no in range(1, seat_count + 1):
        label = f"{no}号"
        try:
            result = await db.execute(
                text("""
                    INSERT INTO order_seats (tenant_id, order_id, seat_no, seat_label)
                    VALUES (:tid, :oid, :no, :label)
                    ON CONFLICT (order_id, seat_no) DO NOTHING
                    RETURNING id, tenant_id, order_id, seat_no, seat_label,
                              sub_total, paid_amount, payment_status
                """),
                {"tid": str(tenant_id), "oid": str(order_id), "no": no, "label": label},
            )
            row = result.fetchone()
            if row:
                rows.append(OrderSeat(
                    id=row[0], tenant_id=row[1], order_id=row[2],
                    seat_no=row[3], seat_label=row[4],
                    sub_total=row[5], paid_amount=row[6], payment_status=row[7],
                ))
        except IntegrityError as exc:
            log.warning("seat_already_exists", order_id=str(order_id), seat_no=no, error=str(exc))

    await db.commit()
    log.info("seats_initialized", order_id=str(order_id), seat_count=seat_count)
    return rows


async def assign_item_to_seat(
    order_item_id: UUID,
    seat_no: Optional[int],
    seat_label: Optional[str],
    tenant_id: UUID,
    db: AsyncSession,
) -> None:
    result = await db.execute(
        text("""
            UPDATE order_items
               SET seat_no = :sno, seat_label = :slabel
             WHERE id = :iid AND tenant_id = :tid
         RETURNING order_id
        """),
        {"sno": seat_no, "slabel": seat_label, "iid": str(order_item_id), "tid": str(tenant_id)},
    )
    row = result.fetchone()
    if not row:
        raise NoResultFound(f"order_item {order_item_id} 不存在或无权限")

    order_id = row[0]
    if seat_no is not None:
        await _recalc_seat_subtotal(order_id=order_id, seat_no=seat_no, tenant_id=tenant_id, db=db)

    await db.commit()
    log.info("item_assigned_to_seat", item_id=str(order_item_id), seat_no=seat_no)


async def _recalc_seat_subtotal(
    order_id: UUID,
    seat_no: int,
    tenant_id: UUID,
    db: AsyncSession,
) -> None:
    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(quantity * unit_price), 0)
              FROM order_items
             WHERE order_id = :oid AND tenant_id = :tid
               AND seat_no = :sno AND is_deleted = FALSE
        """),
        {"oid": str(order_id), "tid": str(tenant_id), "sno": seat_no},
    )
    subtotal = result.scalar() or Decimal("0")

    await db.execute(
        text("""
            UPDATE order_seats
               SET sub_total = :st
             WHERE order_id = :oid AND tenant_id = :tid AND seat_no = :sno
        """),
        {"st": subtotal, "oid": str(order_id), "tid": str(tenant_id), "sno": seat_no},
    )


async def get_seat_summary(
    order_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> list[SeatSummary]:
    seats_result = await db.execute(
        text("""
            SELECT seat_no, seat_label, sub_total, paid_amount, payment_status
              FROM order_seats
             WHERE order_id = :oid AND tenant_id = :tid AND is_deleted = FALSE
             ORDER BY seat_no
        """),
        {"oid": str(order_id), "tid": str(tenant_id)},
    )
    seats = seats_result.fetchall()

    items_result = await db.execute(
        text("""
            SELECT id, dish_name, quantity, unit_price, seat_no
              FROM order_items
             WHERE order_id = :oid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"oid": str(order_id), "tid": str(tenant_id)},
    )
    all_items = items_result.fetchall()

    total_seats = len(seats)
    shared_items = [i for i in all_items if i[4] is None]

    summaries = []
    for seat_row in seats:
        seat_no, seat_label, sub_total, paid_amount, payment_status = seat_row

        seat_specific = [
            SeatItem(
                item_id=str(i[0]),
                name=i[1],
                qty=i[2],
                price=i[3],
                seat_no=i[4],
            )
            for i in all_items if i[4] == seat_no
        ]

        shared = []
        shared_contribution = Decimal("0")
        if total_seats > 0:
            for i in shared_items:
                total_price = i[2] * i[3]
                per_seat = Decimal(math.ceil(float(total_price) / total_seats * 100)) / 100
                shared.append(SeatItem(
                    item_id=str(i[0]),
                    name=i[1],
                    qty=i[2],
                    price=i[3],
                    seat_no=None,
                    share_count=total_seats,
                    share_amount=per_seat,
                ))
                shared_contribution += per_seat

        computed_total = sum(it.price * it.qty for it in seat_specific) + shared_contribution

        summaries.append(SeatSummary(
            seat_no=seat_no,
            seat_label=seat_label,
            items=seat_specific + shared,
            sub_total=computed_total,
            paid_amount=paid_amount,
            payment_status=payment_status,
        ))

    return summaries


async def calculate_split(
    order_id: UUID,
    split_mode: str,
    seat_groups: Optional[list[list[int]]],
    tenant_id: UUID,
    db: AsyncSession,
) -> list[SplitBill]:
    if split_mode not in ("individual", "grouped", "equal"):
        raise ValueError(f"无效的 split_mode: {split_mode}")

    summaries = await get_seat_summary(order_id=order_id, tenant_id=tenant_id, db=db)

    if split_mode == "individual":
        return [
            SplitBill(
                group_label=s.seat_label,
                seat_nos=[s.seat_no],
                items=s.items,
                total_amount=s.sub_total,
            )
            for s in summaries
        ]

    if split_mode == "equal":
        all_items_flat: list[SeatItem] = []
        seen_shared: set[str] = set()
        for s in summaries:
            for it in s.items:
                if it.seat_no is not None:
                    all_items_flat.append(it)
                elif it.item_id not in seen_shared:
                    seen_shared.add(it.item_id)
                    all_items_flat.append(it)
        grand_total = sum(
            (it.share_amount if it.seat_no is None and it.share_amount else it.price * it.qty)
            for it in all_items_flat
        )
        per_person = Decimal(math.ceil(float(grand_total) / len(summaries) * 100)) / 100 if summaries else Decimal("0")
        return [
            SplitBill(
                group_label=s.seat_label,
                seat_nos=[s.seat_no],
                items=s.items,
                total_amount=per_person,
            )
            for s in summaries
        ]

    if not seat_groups:
        raise ValueError("grouped 模式必须提供 seat_groups")

    seat_map = {s.seat_no: s for s in summaries}
    bills = []
    for group in seat_groups:
        group_items: list[SeatItem] = []
        seen_shared_group: set[str] = set()
        group_total = Decimal("0")
        for sno in group:
            s = seat_map.get(sno)
            if not s:
                continue
            for it in s.items:
                if it.seat_no is not None:
                    group_items.append(it)
                    group_total += it.price * it.qty
                elif it.item_id not in seen_shared_group:
                    seen_shared_group.add(it.item_id)
                    group_items.append(it)
                    if it.share_amount:
                        group_total += it.share_amount * len(group)
        label = "+".join(str(sno) for sno in group) + "号"
        bills.append(SplitBill(
            group_label=label,
            seat_nos=group,
            items=group_items,
            total_amount=group_total,
        ))
    return bills


async def generate_self_pay_link(
    order_id: UUID,
    seat_no: int,
    tenant_id: UUID,
    db: AsyncSession,
) -> str:
    result = await db.execute(
        text("""
            SELECT id FROM order_seats
             WHERE order_id = :oid AND tenant_id = :tid AND seat_no = :sno
               AND is_deleted = FALSE
        """),
        {"oid": str(order_id), "tid": str(tenant_id), "sno": seat_no},
    )
    row = result.fetchone()
    if not row:
        raise NoResultFound(f"座位 {seat_no} 不存在")

    token = secrets.token_urlsafe(24)
    log.info("self_pay_link_generated", order_id=str(order_id), seat_no=seat_no, token_prefix=token[:8])
    return token
