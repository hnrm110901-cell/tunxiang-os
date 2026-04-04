"""Customer-facing booking/queue API routes for miniapp-customer.

Maps the miniapp API patterns to the internal service layer.
Routes:
  GET  /api/v1/trade/booking/available-slots  -> 可用时段查询
  POST /api/v1/booking/create                 -> 创建预约
  GET  /api/v1/booking/list                   -> 我的预���列表
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
from uuid import uuid4

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


# ─── 内存 Mock 存储（生产接 DB） ───
_bookings: dict[str, list[dict]] = {}
_queue_tickets: dict[str, list[dict]] = {}


# ═══════════════════════════════════════════════════════════
# 预约可用时段
# ══════════════════════════════════��════════════════════════

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
    is_today = (date == today_str)

    for h in range(11, 21):
        for m in (0, 30):
            time_str = f"{h:02d}:{m:02d}"
            status = "available"
            # 今天已过时段不可选
            if is_today and (h < now.hour or (h == now.hour and m <= now.minute)):
                status = "unavailable"
            # 模拟部分满位（固定规则而非随机，便于测试）
            elif h == 12 and m == 0:
                status = "full"
            elif h == 18 and m == 30:
                status = "full"
            slots.append({"time": time_str, "status": status})

    return _ok({"slots": slots, "date": date, "store_id": store_id})


# ════════════���═══════════════════���══════════════════════════
# 预约 CRUD
# ═══════════════════════��═══════════════════════════════════

class CreateBookingReq(BaseModel):
    store_id: str
    customer_id: Optional[str] = None
    date: str
    time_slot: str
    guests: int = 2
    room_preference: str = "hall"
    remark: str = ""
    meal_period: Optional[str] = None


@router.post("/api/v1/booking/create")
async def create_booking(
    req: CreateBookingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建预约"""
    tenant_id = _get_tenant_id(request)

    # 查询真实门店名
    store_name = "门店"
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        store_row = await db.execute(
            text(
                "SELECT name FROM stores"
                " WHERE id = :store_id"
                " AND tenant_id = NULLIF(current_setting('app.tenant_id', true),'')::UUID"
                " LIMIT 1"
            ),
            {"store_id": req.store_id},
        )
        store_name = store_row.scalar() or "门店"
    except SQLAlchemyError as exc:
        logger.warning("create_booking_store_name_error", error=str(exc), store_id=req.store_id)

    booking = {
        "id": str(uuid4()),
        "tenant_id": tenant_id,
        "store_id": req.store_id,
        "store_name": store_name,
        "customer_id": req.customer_id or "",
        "date": req.date,
        "time_slot": req.time_slot,
        "guests": req.guests,
        "room_preference": req.room_preference,
        "remark": req.remark,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _bookings.setdefault(tenant_id, []).append(booking)
    logger.info("booking_created id=%s store=%s date=%s slot=%s",
                booking["id"], req.store_id, req.date, req.time_slot)
    return _ok(booking)


@router.get("/api/v1/booking/list")
async def list_bookings(
    request: Request,
    store_id: str = Query(""),
    customer_id: str = Query(""),
):
    """获���预约列表"""
    tenant_id = _get_tenant_id(request)
    all_bookings = _bookings.get(tenant_id, [])

    items = all_bookings
    if store_id:
        items = [b for b in items if b["store_id"] == store_id]
    if customer_id:
        items = [b for b in items if b["customer_id"] == customer_id]

    # 按创建时间倒序
    items = sorted(items, key=lambda b: b["created_at"], reverse=True)
    return _ok({"items": items, "total": len(items)})


@router.post("/api/v1/booking/{booking_id}/cancel")
async def cancel_booking(booking_id: str, request: Request):
    """���消预约"""
    tenant_id = _get_tenant_id(request)
    all_bookings = _bookings.get(tenant_id, [])

    for b in all_bookings:
        if b["id"] == booking_id:
            b["status"] = "cancelled"
            logger.info("booking_cancelled id=%s", booking_id)
            return _ok(b)

    return _err_resp("��约不存在")


# ═��══════════════��══════════════════════════════════════════
# 排队
# ══════��════════════════════════���═══════════════════════════

@router.get("/api/v1/queue/summary")
async def queue_summary(request: Request, store_id: str = Query(...)):
    """排队概况"""
    _get_tenant_id(request)
    tickets = _queue_tickets.get(store_id, [])
    waiting = [t for t in tickets if t["status"] == "waiting"]

    # 按桌型汇总
    type_counts: dict[str, int] = {}
    for t in waiting:
        key = t.get("table_type", "medium")
        type_counts[key] = type_counts.get(key, 0) + 1

    items = [
        {"type": "small", "label": "小桌", "waiting": type_counts.get("small", 0), "estimateMin": type_counts.get("small", 0) * 6},
        {"type": "medium", "label": "中���", "waiting": type_counts.get("medium", 0), "estimateMin": type_counts.get("medium", 0) * 6},
        {"type": "large", "label": "大桌", "waiting": type_counts.get("large", 0), "estimateMin": type_counts.get("large", 0) * 6},
    ]
    return _ok({"items": items})


class TakeQueueReq(BaseModel):
    store_id: str
    customer_id: str = ""
    guest_range: str = ""


@router.post("/api/v1/queue/take")
async def take_queue(req: TakeQueueReq, request: Request):
    """取号"""
    tenant_id = _get_tenant_id(request)
    store_id = req.store_id
    tickets = _queue_tickets.setdefault(store_id, [])

    # 检查是否已有排队
    for t in tickets:
        if t["customer_id"] == req.customer_id and t["status"] == "waiting":
            return _err_resp("您已在排队中")

    # 映射guest_range到table_type
    range_map = {"1-2": "small", "3-4": "medium", "5+": "large"}
    table_type = range_map.get(req.guest_range, "medium")

    # 生成排队号
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_tickets = [t for t in tickets if t.get("date") == today]
    queue_no = len(today_tickets) + 1
    prefix_map = {"small": "S", "medium": "M", "large": "L"}
    ticket_no = prefix_map.get(table_type, "M") + str(queue_no).zfill(3)

    # 等待桌数
    waiting = sum(1 for t in tickets if t["status"] == "waiting" and t.get("table_type") == table_type)

    ticket = {
        "id": str(uuid4()),
        "tenant_id": tenant_id,
        "store_id": store_id,
        "customer_id": req.customer_id,
        "date": today,
        "ticketNo": ticket_no,
        "queueLabel": {"small": "小���", "medium": "中桌", "large": "大桌"}.get(table_type, "中桌"),
        "table_type": table_type,
        "guests": req.guest_range,
        "ahead": waiting,
        "estimateMin": waiting * 6,
        "status": "waiting",
        "createdAt": datetime.now(timezone.utc).strftime("%H:%M"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tickets.append(ticket)
    logger.info("queue_take store=%s ticket=%s type=%s", store_id, ticket_no, table_type)
    return _ok(ticket)


@router.get("/api/v1/queue/my-ticket")
async def my_ticket(
    request: Request,
    store_id: str = Query(...),
    customer_id: str = Query(""),
):
    """查询我的排队票"""
    _get_tenant_id(request)
    tickets = _queue_tickets.get(store_id, [])

    for t in reversed(tickets):
        if t["customer_id"] == customer_id and t["status"] in ("waiting", "called"):
            # 重新计算前面等待数
            ahead = sum(
                1 for x in tickets
                if x["status"] == "waiting"
                and x.get("table_type") == t.get("table_type")
                and x["created_at"] < t["created_at"]
            )
            t["ahead"] = ahead
            t["estimateMin"] = ahead * 6
            return _ok(t)

    return _ok(None)


@router.post("/api/v1/queue/{ticket_id}/cancel")
async def cancel_queue(ticket_id: str, request: Request):
    """取消排队"""
    _get_tenant_id(request)

    for store_tickets in _queue_tickets.values():
        for t in store_tickets:
            if t["id"] == ticket_id:
                t["status"] = "cancelled"
                logger.info("queue_cancelled id=%s ticket=%s", ticket_id, t.get("ticketNo"))
                return _ok(t)

    return _err_resp("排队票不存在")


@router.get("/api/v1/queue/estimate")
async def queue_estimate(
    request: Request,
    store_id: str = Query(...),
    guest_range: str = Query(""),
):
    """预估等���时间"""
    _get_tenant_id(request)
    range_map = {"1-2": "small", "3-4": "medium", "5+": "large"}
    table_type = range_map.get(guest_range, "medium")
    tickets = _queue_tickets.get(store_id, [])
    waiting = sum(1 for t in tickets if t["status"] == "waiting" and t.get("table_type") == table_type)

    return _ok({
        "waiting": waiting,
        "estimate_min": waiting * 6,
    })
