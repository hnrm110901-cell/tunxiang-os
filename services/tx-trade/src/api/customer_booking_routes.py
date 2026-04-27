"""Customer-facing booking/queue API routes for miniapp-customer.

Maps the miniapp API patterns to the internal service layer.
Routes:
  GET  /api/v1/trade/booking/available-slots  -> 可用时段查询
  POST /api/v1/booking/create                 -> 创建预约
  GET  /api/v1/booking/list                   -> 我的预约列表
  POST /api/v1/booking/{id}/cancel            -> 取消预约
  GET  /api/v1/queue/summary                  -> 排队概况
  POST /api/v1/queue/take                     -> 取号
  GET  /api/v1/queue/my-ticket                -> 我的排队票
  POST /api/v1/queue/{id}/cancel              -> 取消排队
  GET  /api/v1/queue/estimate                 -> 预估等待时间
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["customer-booking"])

# ─── 通用辅助 ───


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err_resp(msg: str) -> dict:
    return {"ok": False, "data": None, "error": {"message": msg}}


def _get_tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ═══════════════════════════════════════════════════════════
# 预约可用时段
# ═══════════════════════════════════════════════════════════


@router.get("/api/v1/trade/booking/available-slots")
async def get_available_slots(
    request: Request,
    store_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
):
    """查询指定门店和日期的可用预约时段。

    返回 slots 数组，每个元素: { time: "HH:MM", status: "available"|"full"|"unavailable" }
    """
    _get_tenant_id(request)

    # Mock: 生成11:00-21:00每30分钟时段
    slots = []
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    is_today = date == today_str

    for h in range(11, 21):
        for m in (0, 30):
            time_str = f"{h:02d}:{m:02d}"
            status = "available"
            # 今天已过时段不可选
            if is_today and (h < now.hour or (h == now.hour and m <= now.minute)):
                status = "unavailable"
            # 模拟部分满位（固定规则而非随机，便于测试）
            elif h == 12 and m == 0 or h == 18 and m == 30:
                status = "full"
            slots.append({"time": time_str, "status": status})

    return _ok({"slots": slots, "date": date, "store_id": store_id})


# ═══════════════════════════════════════════════════════════
# 预约 CRUD
# ═══════════════════════════════════════════════════════════


class CreateBookingReq(BaseModel):
    store_id: str
    customer_name: str
    customer_phone: str
    party_size: int = 2
    booking_date: str  # YYYY-MM-DD
    booking_time: str  # HH:MM
    table_type: Optional[str] = None
    special_request: Optional[str] = None
    source: str = "miniapp"


@router.post("/api/v1/booking/create")
async def create_booking(
    req: CreateBookingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建预约"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                INSERT INTO customer_bookings
                    (tenant_id, store_id, customer_name, customer_phone,
                     party_size, booking_date, booking_time, table_type,
                     special_request, source)
                VALUES
                    (:tenant_id, :store_id, :customer_name, :customer_phone,
                     :party_size, :booking_date, :booking_time, :table_type,
                     :special_request, :source)
                RETURNING id, status, created_at
            """),
            {
                "tenant_id": tenant_id,
                "store_id": req.store_id,
                "customer_name": req.customer_name,
                "customer_phone": req.customer_phone,
                "party_size": req.party_size,
                "booking_date": req.booking_date,
                "booking_time": req.booking_time,
                "table_type": req.table_type,
                "special_request": req.special_request,
                "source": req.source,
            },
        )
        await db.commit()
        rec = row.mappings().one()
        logger.info(
            "booking_created id=%s store=%s date=%s slot=%s",
            rec["id"],
            req.store_id,
            req.booking_date,
            req.booking_time,
        )
        return _ok(
            {
                "id": str(rec["id"]),
                "tenant_id": tenant_id,
                "store_id": req.store_id,
                "customer_name": req.customer_name,
                "customer_phone": req.customer_phone,
                "party_size": req.party_size,
                "booking_date": req.booking_date,
                "booking_time": req.booking_time,
                "table_type": req.table_type,
                "special_request": req.special_request,
                "status": rec["status"],
                "source": req.source,
                "created_at": rec["created_at"].isoformat(),
            }
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_booking_error store=%s error=%s", req.store_id, str(exc))
        return _err_resp("创建预约失败")


@router.get("/api/v1/booking/list")
async def list_bookings(
    request: Request,
    store_id: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """获取预约列表"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)
        rows = await db.execute(
            text("""
                SELECT id, store_id, customer_name, customer_phone,
                       party_size, booking_date, booking_time, table_type,
                       special_request, status, source,
                       cancelled_at, cancel_reason, created_at, updated_at
                FROM customer_bookings
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND (:store_id = '' OR store_id = :store_id::UUID)
                  AND is_deleted = FALSE
                ORDER BY booking_date, booking_time
                LIMIT 50
            """),
            {"store_id": store_id},
        )
        items = [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "customer_name": r["customer_name"],
                "customer_phone": r["customer_phone"],
                "party_size": r["party_size"],
                "booking_date": str(r["booking_date"]),
                "booking_time": r["booking_time"],
                "table_type": r["table_type"],
                "special_request": r["special_request"],
                "status": r["status"],
                "source": r["source"],
                "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
                "cancel_reason": r["cancel_reason"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows.mappings()
        ]
        return _ok({"items": items, "total": len(items)})
    except SQLAlchemyError as exc:
        logger.error("list_bookings_error store=%s error=%s", store_id, str(exc))
        return _err_resp("查询预约列表失败")


@router.post("/api/v1/booking/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取消预约"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                UPDATE customer_bookings
                SET status = 'cancelled',
                    cancelled_at = NOW(),
                    updated_at = NOW()
                WHERE id = :bid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"bid": booking_id},
        )
        await db.commit()
        rec = row.mappings().first()
        if not rec:
            return _err_resp("预约不存在")
        logger.info("booking_cancelled id=%s", booking_id)
        return _ok({"id": str(rec["id"]), "status": "cancelled"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("cancel_booking_error id=%s error=%s", booking_id, str(exc))
        return _err_resp("取消预约失败")


# ═══════════════════════════════════════════════════════════
# 排队
# ═══════════════════════════════════════════════════════════


@router.get("/api/v1/queue/summary")
async def queue_summary(request: Request, store_id: str = Query(...)):
    """排队概况（静态 Mock，实际应从 queue_tickets 聚合）"""
    _get_tenant_id(request)
    items = [
        {"type": "small", "label": "小桌", "waiting": 0, "estimateMin": 0},
        {"type": "medium", "label": "中桌", "waiting": 0, "estimateMin": 0},
        {"type": "large", "label": "大桌", "waiting": 0, "estimateMin": 0},
    ]
    return _ok({"items": items})


class TakeQueueReq(BaseModel):
    store_id: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    party_size: int = 2
    guest_range: str = ""  # "1-2" / "3-4" / "5+"
    queue_type: str = "normal"


@router.post("/api/v1/queue/take")
async def take_queue(
    req: TakeQueueReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取号"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        # 生成当日流水号（A001 格式）
        count_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM queue_tickets
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND store_id = :sid::UUID
                  AND created_at::DATE = CURRENT_DATE
                  AND is_deleted = FALSE
            """),
            {"sid": req.store_id},
        )
        today_count = (count_row.scalar() or 0) + 1
        ticket_no = "A" + str(today_count).zfill(3)

        row = await db.execute(
            text("""
                INSERT INTO queue_tickets
                    (tenant_id, store_id, ticket_no, customer_name, customer_phone,
                     party_size, queue_type)
                VALUES
                    (:tenant_id, :store_id, :ticket_no, :customer_name, :customer_phone,
                     :party_size, :queue_type)
                RETURNING id, status, created_at
            """),
            {
                "tenant_id": tenant_id,
                "store_id": req.store_id,
                "ticket_no": ticket_no,
                "customer_name": req.customer_name,
                "customer_phone": req.customer_phone,
                "party_size": req.party_size,
                "queue_type": req.queue_type,
            },
        )
        await db.commit()
        rec = row.mappings().one()

        # 前方等待数
        waiting_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM queue_tickets
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND store_id = :sid::UUID
                  AND status = 'waiting'
                  AND is_deleted = FALSE
            """),
            {"sid": req.store_id},
        )
        ahead = max(0, (waiting_row.scalar() or 1) - 1)

        logger.info("queue_take store=%s ticket=%s", req.store_id, ticket_no)
        return _ok(
            {
                "id": str(rec["id"]),
                "tenant_id": tenant_id,
                "store_id": req.store_id,
                "ticketNo": ticket_no,
                "customer_name": req.customer_name,
                "customer_phone": req.customer_phone,
                "party_size": req.party_size,
                "queue_type": req.queue_type,
                "status": rec["status"],
                "ahead": ahead,
                "estimateMin": ahead * 6,
                "createdAt": rec["created_at"].strftime("%H:%M"),
                "created_at": rec["created_at"].isoformat(),
            }
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("take_queue_error store=%s error=%s", req.store_id, str(exc))
        return _err_resp("取号失败")


@router.get("/api/v1/queue/my-ticket")
async def my_ticket(
    request: Request,
    store_id: str = Query(...),
    ticket_id: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """查询我的排队票"""
    tenant_id = _get_tenant_id(request)
    if not ticket_id:
        return _ok(None)
    try:
        await _set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                SELECT id, store_id, ticket_no, customer_name, customer_phone,
                       party_size, queue_type, status,
                       called_at, seated_at, cancelled_at, wait_minutes,
                       created_at, updated_at
                FROM queue_tickets
                WHERE id = :tid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND is_deleted = FALSE
            """),
            {"tid": ticket_id},
        )
        rec = row.mappings().first()
        if not rec:
            return _ok(None)

        # 前方等待数
        ahead_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM queue_tickets
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND store_id = :sid::UUID
                  AND status = 'waiting'
                  AND queue_type = :qt
                  AND created_at < :created_at
                  AND is_deleted = FALSE
            """),
            {
                "sid": str(rec["store_id"]),
                "qt": rec["queue_type"],
                "created_at": rec["created_at"],
            },
        )
        ahead = ahead_row.scalar() or 0

        return _ok(
            {
                "id": str(rec["id"]),
                "store_id": str(rec["store_id"]),
                "ticketNo": rec["ticket_no"],
                "customer_name": rec["customer_name"],
                "customer_phone": rec["customer_phone"],
                "party_size": rec["party_size"],
                "queue_type": rec["queue_type"],
                "status": rec["status"],
                "ahead": ahead,
                "estimateMin": ahead * 6,
                "called_at": rec["called_at"].isoformat() if rec["called_at"] else None,
                "seated_at": rec["seated_at"].isoformat() if rec["seated_at"] else None,
                "cancelled_at": rec["cancelled_at"].isoformat() if rec["cancelled_at"] else None,
                "wait_minutes": rec["wait_minutes"],
                "createdAt": rec["created_at"].strftime("%H:%M"),
                "created_at": rec["created_at"].isoformat(),
            }
        )
    except SQLAlchemyError as exc:
        logger.error("my_ticket_error tid=%s error=%s", ticket_id, str(exc))
        return _err_resp("查询排队票失败")


@router.post("/api/v1/queue/{ticket_id}/cancel")
async def cancel_queue(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取消排队"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                UPDATE queue_tickets
                SET status = 'cancelled',
                    cancelled_at = NOW(),
                    updated_at = NOW()
                WHERE id = :tid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND is_deleted = FALSE
                RETURNING id, ticket_no
            """),
            {"tid": ticket_id},
        )
        await db.commit()
        rec = row.mappings().first()
        if not rec:
            return _err_resp("排队票不存在")
        logger.info("queue_cancelled id=%s ticket=%s", ticket_id, rec["ticket_no"])
        return _ok({"id": str(rec["id"]), "status": "cancelled"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("cancel_queue_error tid=%s error=%s", ticket_id, str(exc))
        return _err_resp("取消排队失败")


@router.get("/api/v1/queue/estimate")
async def queue_estimate(
    request: Request,
    store_id: str = Query(...),
    guest_range: str = Query(""),
):
    """预估等待时间"""
    _get_tenant_id(request)
    # 静态估算（不依赖 DB），与 queue_summary 保持一致
    return _ok(
        {
            "waiting": 0,
            "estimate_min": 0,
        }
    )
