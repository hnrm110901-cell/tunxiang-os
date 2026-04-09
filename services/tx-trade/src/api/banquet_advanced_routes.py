"""宴席高级管理 API — 排菜方案 + 场次管理 + 分席结账 + 经营分析

端点：
  POST /api/v1/banquet/menu-plan              — 创建排菜方案
  GET  /api/v1/banquet/menu-plans             — 方案列表
  GET  /api/v1/banquet/menu-plans/{plan_id}   — 方案详情
  POST /api/v1/banquet/sessions               — 创建宴席场次
  GET  /api/v1/banquet/sessions               — 场次列表
  PUT  /api/v1/banquet/sessions/{id}/status    — 场次状态流转
  POST /api/v1/banquet/sessions/{id}/split-bill — 分席结账
  GET  /api/v1/banquet/sessions/{id}/bills     — 各席账单
  GET  /api/v1/banquet/analytics              — 宴席经营分析
"""
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/banquet", tags=["宴席高级管理"])


# ─── 依赖注入 ──
async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 请求模型 ──

class MenuPlanCreate(BaseModel):
    name: str = Field(..., max_length=100)
    guest_count: int = Field(..., ge=1)
    budget_fen: Optional[int] = Field(None, ge=0)
    dishes: list[dict] = Field(..., description="[{dish_id, dish_name, qty, unit_price_fen}]")


class SessionCreate(BaseModel):
    store_id: str
    session_date: str = Field(..., description="YYYY-MM-DD")
    time_slot: str = Field("dinner", description="lunch/dinner/custom")
    room_ids: list[str] = Field(default_factory=list)
    table_count: int = Field(1, ge=1)
    guest_count: int = Field(..., ge=1)
    menu_plan_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    deposit_fen: int = Field(0, ge=0)
    notes: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str = Field(..., description="confirmed/preparing/serving/completed/cancelled")


class SplitBillRequest(BaseModel):
    split_mode: str = Field("by_table", description="by_table/by_person/custom_ratio")
    tables: list[dict] = Field(..., description="[{table_no, ratio?, amount_fen?}]")


# ─── 排菜方案 ──

@router.post("/menu-plan", summary="创建排菜方案")
async def create_menu_plan(
    body: MenuPlanCreate,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    total_price = sum(d.get("unit_price_fen", 0) * d.get("qty", 1) for d in body.dishes)
    total_cost = int(total_price * 0.35)  # 估算成本35%
    margin = round((1 - total_cost / total_price) * 100, 2) if total_price > 0 else 0

    result = await db.execute(
        text("""
            INSERT INTO banquet_menu_plans
                (tenant_id, name, guest_count, budget_fen, dishes, total_cost_fen, total_price_fen, margin_rate)
            VALUES (:tid::UUID, :name, :gc, :budget, :dishes::JSONB, :cost, :price, :margin)
            RETURNING id, created_at
        """),
        {"tid": tenant_id, "name": body.name, "gc": body.guest_count,
         "budget": body.budget_fen, "dishes": json.dumps(body.dishes),
         "cost": total_cost, "price": total_price, "margin": margin},
    )
    row = result.mappings().first()
    await db.commit()

    return {"ok": True, "data": {"id": str(row["id"]), "name": body.name,
            "total_price_fen": total_price, "margin_rate": margin}}


@router.get("/menu-plans", summary="排菜方案列表")
async def list_menu_plans(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    count_r = await db.execute(text(
        "SELECT COUNT(*) FROM banquet_menu_plans WHERE is_deleted=FALSE"
    ))
    total = count_r.scalar() or 0

    result = await db.execute(text("""
        SELECT id, name, guest_count, budget_fen, total_price_fen, margin_rate, status, created_at
        FROM banquet_menu_plans WHERE is_deleted=FALSE
        ORDER BY created_at DESC LIMIT :lim OFFSET :off
    """), {"lim": size, "off": (page - 1) * size})
    items = [dict(r) for r in result.mappings().all()]
    for item in items:
        for k, v in item.items():
            if isinstance(v, uuid.UUID):
                item[k] = str(v)
            elif isinstance(v, (datetime, date)):
                item[k] = v.isoformat()

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/menu-plans/{plan_id}", summary="方案详情")
async def get_menu_plan(
    plan_id: str, db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    result = await db.execute(text("""
        SELECT * FROM banquet_menu_plans WHERE id = :pid::UUID AND is_deleted=FALSE
    """), {"pid": plan_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="方案不存在")
    data = dict(row)
    for k, v in data.items():
        if isinstance(v, uuid.UUID):
            data[k] = str(v)
        elif isinstance(v, (datetime, date)):
            data[k] = v.isoformat()
    return {"ok": True, "data": data}


# ─── 场次管理 ──

@router.post("/sessions", summary="创建宴席场次")
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    result = await db.execute(
        text("""
            INSERT INTO banquet_sessions
                (tenant_id, store_id, menu_plan_id, session_date, time_slot,
                 room_ids, table_count, guest_count, contact_name, contact_phone,
                 deposit_fen, notes)
            VALUES (:tid::UUID, :sid::UUID, :mpid, :sdate::DATE, :slot,
                    :rooms::JSONB, :tc, :gc, :cn, :cp, :dep, :notes)
            RETURNING id, created_at
        """),
        {"tid": tenant_id, "sid": body.store_id,
         "mpid": body.menu_plan_id, "sdate": body.session_date,
         "slot": body.time_slot, "rooms": json.dumps(body.room_ids),
         "tc": body.table_count, "gc": body.guest_count,
         "cn": body.contact_name, "cp": body.contact_phone,
         "dep": body.deposit_fen, "notes": body.notes},
    )
    row = result.mappings().first()
    await db.commit()
    return {"ok": True, "data": {"id": str(row["id"]), "session_date": body.session_date,
            "status": "confirmed"}}


@router.get("/sessions", summary="场次列表")
async def list_sessions(
    start_date: Optional[str] = None, end_date: Optional[str] = None,
    status: Optional[str] = None, store_id: Optional[str] = None,
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    wheres = ["is_deleted=FALSE"]
    params: dict = {"lim": size, "off": (page - 1) * size}
    if start_date:
        wheres.append("session_date >= :sd::DATE")
        params["sd"] = start_date
    if end_date:
        wheres.append("session_date <= :ed::DATE")
        params["ed"] = end_date
    if status:
        wheres.append("status = :st")
        params["st"] = status
    if store_id:
        wheres.append("store_id = :sid::UUID")
        params["sid"] = store_id
    w = " AND ".join(wheres)

    count_r = await db.execute(text(f"SELECT COUNT(*) FROM banquet_sessions WHERE {w}"), params)
    total = count_r.scalar() or 0

    result = await db.execute(text(f"""
        SELECT id, store_id, session_date, time_slot, table_count, guest_count,
               contact_name, status, total_amount_fen, deposit_fen, created_at
        FROM banquet_sessions WHERE {w}
        ORDER BY session_date DESC, created_at DESC LIMIT :lim OFFSET :off
    """), params)
    items = []
    for r in result.mappings().all():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, uuid.UUID):
                d[k] = str(v)
            elif isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        items.append(d)

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/sessions/{session_id}/status", summary="场次状态流转")
async def update_session_status(
    session_id: str, body: StatusUpdate,
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    valid_transitions = {
        "confirmed": ["preparing", "cancelled"],
        "preparing": ["serving", "cancelled"],
        "serving": ["completed"],
    }
    # 查当前状态
    cur = await db.execute(text(
        "SELECT status FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted=FALSE"
    ), {"sid": session_id})
    row = cur.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="场次不存在")

    current = row["status"]
    allowed = valid_transitions.get(current, [])
    if body.status not in allowed:
        raise HTTPException(status_code=400,
                            detail=f"不允许从 {current} 转到 {body.status}，允许: {allowed}")

    await db.execute(text("""
        UPDATE banquet_sessions SET status = :st, updated_at = now()
        WHERE id = :sid::UUID
    """), {"st": body.status, "sid": session_id})
    await db.commit()
    return {"ok": True, "data": {"session_id": session_id, "status": body.status}}


# ─── 分席结账 ──

@router.post("/sessions/{session_id}/split-bill", summary="分席结账")
async def split_bill(
    session_id: str, body: SplitBillRequest,
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    # 查场次总金额
    sess = await db.execute(text(
        "SELECT total_amount_fen, table_count FROM banquet_sessions WHERE id=:sid::UUID AND is_deleted=FALSE"
    ), {"sid": session_id})
    s = sess.mappings().first()
    if not s:
        raise HTTPException(status_code=404, detail="场次不存在")

    bills = []
    for t in body.tables:
        table_no = t["table_no"]
        if body.split_mode == "by_table" and s["table_count"] > 0:
            amount = s["total_amount_fen"] // s["table_count"]
        elif body.split_mode == "custom_ratio":
            ratio = t.get("ratio", 1.0)
            amount = int(s["total_amount_fen"] * ratio)
        else:
            amount = t.get("amount_fen", 0)

        r = await db.execute(text("""
            INSERT INTO banquet_split_bills (tenant_id, session_id, table_no, split_mode, ratio, amount_fen)
            VALUES (:tid::UUID, :sid::UUID, :tn, :mode, :ratio, :amt)
            RETURNING id
        """), {"tid": tenant_id, "sid": session_id, "tn": table_no,
               "mode": body.split_mode, "ratio": t.get("ratio"), "amt": amount})
        bill_row = r.mappings().first()
        bills.append({"id": str(bill_row["id"]), "table_no": table_no, "amount_fen": amount})

    await db.commit()
    return {"ok": True, "data": {"session_id": session_id, "bills": bills}}


@router.get("/sessions/{session_id}/bills", summary="各席账单")
async def get_session_bills(
    session_id: str,
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    result = await db.execute(text("""
        SELECT id, table_no, split_mode, ratio, amount_fen, paid, paid_at, payment_method
        FROM banquet_split_bills
        WHERE session_id = :sid::UUID AND is_deleted=FALSE
        ORDER BY table_no
    """), {"sid": session_id})
    items = []
    for r in result.mappings().all():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, uuid.UUID):
                d[k] = str(v)
            elif isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        items.append(d)
    return {"ok": True, "data": {"session_id": session_id, "bills": items}}


# ─── 宴席经营分析 ──

@router.get("/analytics", summary="宴席经营分析")
async def banquet_analytics(
    start_date: Optional[str] = None, end_date: Optional[str] = None,
    store_id: Optional[str] = None,
    db: AsyncSession = Depends(_get_tenant_db), tenant_id: str = Depends(_tid),
):
    wheres = ["is_deleted=FALSE", "status != 'cancelled'"]
    params: dict = {}
    if start_date:
        wheres.append("session_date >= :sd::DATE")
        params["sd"] = start_date
    if end_date:
        wheres.append("session_date <= :ed::DATE")
        params["ed"] = end_date
    if store_id:
        wheres.append("store_id = :sid::UUID")
        params["sid"] = store_id
    w = " AND ".join(wheres)

    result = await db.execute(text(f"""
        SELECT
            COUNT(*) AS session_count,
            COALESCE(SUM(total_amount_fen), 0) AS total_revenue_fen,
            COALESCE(SUM(guest_count), 0) AS total_guests,
            CASE WHEN SUM(guest_count) > 0
                 THEN SUM(total_amount_fen) / SUM(guest_count)
                 ELSE 0 END AS avg_per_guest_fen,
            CASE WHEN COUNT(*) > 0
                 THEN SUM(total_amount_fen) / COUNT(*)
                 ELSE 0 END AS avg_per_session_fen
        FROM banquet_sessions WHERE {w}
    """), params)
    stats = dict(result.mappings().first())

    # TOP5排菜方案
    top_plans = await db.execute(text(f"""
        SELECT mp.name, COUNT(bs.id) AS usage_count,
               COALESCE(SUM(bs.total_amount_fen), 0) AS revenue_fen
        FROM banquet_sessions bs
        JOIN banquet_menu_plans mp ON mp.id = bs.menu_plan_id
        WHERE bs.is_deleted=FALSE AND bs.status != 'cancelled'
        {"AND bs.session_date >= :sd::DATE" if start_date else ""}
        {"AND bs.session_date <= :ed::DATE" if end_date else ""}
        GROUP BY mp.name ORDER BY usage_count DESC LIMIT 5
    """), params)
    top = [dict(r) for r in top_plans.mappings().all()]

    return {"ok": True, "data": {**stats, "top_menu_plans": top}}
