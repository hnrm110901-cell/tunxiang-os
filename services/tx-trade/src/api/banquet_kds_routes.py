"""宴会 KDS 出品管理 API — 场次出品调度

端点：
  GET  /api/v1/banquet/kds/sessions                          — KDS待出品场次列表（含出品进度）
  GET  /api/v1/banquet/kds/{session_id}/dishes               — 场次排菜出品状态
  POST /api/v1/banquet/kds/{session_id}/dishes/{dish_id}/serve — 标记出品
  POST /api/v1/banquet/kds/{session_id}/call                 — 叫菜（通知厨房）
  GET  /api/v1/banquet/kds/{session_id}/progress             — 出品进度汇总
"""

import asyncio
import json
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import KdsEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/banquet/kds", tags=["宴会KDS"])


# ─── 依赖注入 ────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class ServeRequest(BaseModel):
    served_qty: int = Field(1, ge=1, description="出品数量")
    notes: Optional[str] = Field(None, max_length=200)


class CallKitchenRequest(BaseModel):
    dish_id: Optional[str] = Field(None, description="指定叫某道菜，为空则叫全部")
    message: Optional[str] = Field(None, max_length=200, description="叫菜备注")


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _serialize(d: dict) -> dict:
    """将 UUID/datetime/date 转为 str，用于 JSON 序列化。"""
    out = {}
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ─── KDS 场次列表 ─────────────────────────────────────────────────────────────


@router.get("/sessions", summary="KDS待出品场次列表（含出品进度）")
async def kds_sessions(
    store_id: Optional[str] = None,
    session_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """返回状态为 preparing/serving 的场次，含每场次出品进度。"""
    wheres = ["bs.is_deleted = FALSE", "bs.status IN ('preparing', 'serving')"]
    params: dict = {"lim": size, "off": (page - 1) * size}

    if store_id:
        wheres.append("bs.store_id = :sid::UUID")
        params["sid"] = store_id
    if session_date:
        wheres.append("bs.session_date = :sdate::DATE")
        params["sdate"] = session_date

    w = " AND ".join(wheres)

    count_r = await db.execute(text(f"SELECT COUNT(*) FROM banquet_sessions bs WHERE {w}"), params)
    total = count_r.scalar() or 0

    result = await db.execute(
        text(f"""
            SELECT
                bs.id,
                bs.store_id,
                bs.session_date,
                bs.time_slot,
                bs.guest_count,
                bs.table_count,
                bs.contact_name,
                bs.status,
                bs.room_ids,
                COALESCE(prog.total_dishes, 0)   AS total_dishes,
                COALESCE(prog.served_dishes, 0)  AS served_dishes,
                COALESCE(prog.serving_dishes, 0) AS serving_dishes
            FROM banquet_sessions bs
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)                                            AS total_dishes,
                    COUNT(*) FILTER (WHERE serve_status = 'served')    AS served_dishes,
                    COUNT(*) FILTER (WHERE serve_status = 'serving')   AS serving_dishes
                FROM banquet_kds_dishes bkd
                WHERE bkd.session_id = bs.id AND bkd.is_deleted = FALSE
            ) prog ON TRUE
            WHERE {w}
            ORDER BY bs.session_date ASC, bs.created_at ASC
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    items = [_serialize(dict(r)) for r in result.mappings().all()]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


# ─── 场次排菜出品状态 ─────────────────────────────────────────────────────────


@router.get("/{session_id}/dishes", summary="场次排菜出品状态")
async def session_dishes(
    session_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """返回场次内每道菜的当前出品状态（pending/serving/served）。"""
    # 验证场次存在
    sess_r = await db.execute(
        text("SELECT id, status FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted = FALSE"),
        {"sid": session_id},
    )
    sess = sess_r.mappings().first()
    if not sess:
        raise HTTPException(status_code=404, detail="场次不存在")

    result = await db.execute(
        text("""
            SELECT
                bkd.id,
                bkd.session_id,
                bkd.dish_id,
                bkd.dish_name,
                bkd.total_qty,
                bkd.served_qty,
                bkd.serve_status,
                bkd.called_at,
                bkd.served_at,
                bkd.sequence_no,
                bkd.notes
            FROM banquet_kds_dishes bkd
            WHERE bkd.session_id = :sid::UUID AND bkd.is_deleted = FALSE
            ORDER BY bkd.sequence_no ASC, bkd.created_at ASC
        """),
        {"sid": session_id},
    )
    items = [_serialize(dict(r)) for r in result.mappings().all()]

    # 如果 KDS 菜品记录为空，则从排菜方案自动生成
    if not items:
        items = await _init_kds_dishes_from_plan(db, session_id, tenant_id)

    return {"ok": True, "data": {"session_id": session_id, "dishes": items}}


async def _init_kds_dishes_from_plan(db: AsyncSession, session_id: str, tenant_id: str) -> list[dict]:
    """从排菜方案初始化 KDS 菜品记录（懒加载）。"""
    sess_r = await db.execute(
        text("""
            SELECT bs.menu_plan_id, mp.dishes
            FROM banquet_sessions bs
            LEFT JOIN banquet_menu_plans mp ON mp.id = bs.menu_plan_id
            WHERE bs.id = :sid::UUID AND bs.is_deleted = FALSE
        """),
        {"sid": session_id},
    )
    sess = sess_r.mappings().first()
    if not sess or not sess["dishes"]:
        return []

    dishes = sess["dishes"] if isinstance(sess["dishes"], list) else json.loads(sess["dishes"])
    items = []
    for seq, d in enumerate(dishes, start=1):
        r = await db.execute(
            text("""
                INSERT INTO banquet_kds_dishes
                    (tenant_id, session_id, dish_id, dish_name, total_qty, served_qty,
                     serve_status, sequence_no)
                VALUES
                    (:tid::UUID, :sid::UUID, :did, :dname, :qty, 0, 'pending', :seq)
                RETURNING id, dish_id, dish_name, total_qty, served_qty, serve_status,
                          sequence_no, called_at, served_at, notes
            """),
            {
                "tid": tenant_id,
                "sid": session_id,
                "did": str(d.get("dish_id", "")),
                "dname": d.get("dish_name", ""),
                "qty": d.get("qty", 1),
                "seq": seq,
            },
        )
        row = r.mappings().first()
        items.append(_serialize(dict(row) | {"session_id": session_id}))

    await db.commit()
    return items


# ─── 标记出品 ────────────────────────────────────────────────────────────────


@router.post("/{session_id}/dishes/{dish_id}/serve", summary="标记出品（更新状态+事件）")
async def serve_dish(
    session_id: str,
    dish_id: str,
    body: ServeRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """将菜品状态推进：pending→serving 或 serving→served。"""
    row_r = await db.execute(
        text("""
            SELECT id, dish_name, total_qty, served_qty, serve_status
            FROM banquet_kds_dishes
            WHERE id = :did::UUID AND session_id = :sid::UUID AND is_deleted = FALSE
        """),
        {"did": dish_id, "sid": session_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="菜品记录不存在")

    current_status = row["serve_status"]
    if current_status == "served":
        raise HTTPException(status_code=400, detail="该菜品已出品完毕")

    new_served_qty = row["served_qty"] + body.served_qty
    if new_served_qty > row["total_qty"]:
        raise HTTPException(
            status_code=400,
            detail=f"出品数量超出总数：{row['total_qty']} - {row['served_qty']} = {row['total_qty'] - row['served_qty']}",
        )

    new_status = "served" if new_served_qty >= row["total_qty"] else "serving"
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            UPDATE banquet_kds_dishes
            SET served_qty   = :qty,
                serve_status = :st,
                served_at    = CASE WHEN :st = 'served' THEN :now ELSE served_at END,
                notes        = COALESCE(:notes, notes),
                updated_at   = :now
            WHERE id = :did::UUID
        """),
        {
            "qty": new_served_qty,
            "st": new_status,
            "now": now,
            "notes": body.notes,
            "did": dish_id,
        },
    )
    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=KdsEventType.ORDER_READY,
            tenant_id=tenant_id,
            stream_id=session_id,
            payload={
                "session_id": session_id,
                "dish_id": dish_id,
                "dish_name": row["dish_name"],
                "served_qty": new_served_qty,
                "total_qty": row["total_qty"],
                "serve_status": new_status,
            },
            source_service="tx-trade",
        )
    )

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "dish_name": row["dish_name"],
            "serve_status": new_status,
            "served_qty": new_served_qty,
            "total_qty": row["total_qty"],
        },
    }


# ─── 叫菜 ────────────────────────────────────────────────────────────────────


@router.post("/{session_id}/call", summary="叫菜（通知厨房）")
async def call_kitchen(
    session_id: str,
    body: CallKitchenRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """向厨房发出叫菜指令，更新 called_at 时间戳，旁路写入 KDS 事件。"""
    # 验证场次
    sess_r = await db.execute(
        text("SELECT id FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted = FALSE"),
        {"sid": session_id},
    )
    if not sess_r.mappings().first():
        raise HTTPException(status_code=404, detail="场次不存在")

    now = datetime.now(timezone.utc)

    if body.dish_id:
        # 叫特定菜品
        r = await db.execute(
            text("""
                UPDATE banquet_kds_dishes
                SET called_at  = :now,
                    serve_status = CASE WHEN serve_status = 'pending' THEN 'serving' ELSE serve_status END,
                    updated_at = :now
                WHERE id = :did::UUID AND session_id = :sid::UUID AND is_deleted = FALSE
                RETURNING id, dish_name, serve_status
            """),
            {"now": now, "did": body.dish_id, "sid": session_id},
        )
        updated = r.mappings().first()
        if not updated:
            raise HTTPException(status_code=404, detail="菜品不存在")
        called_dishes = [{"id": str(updated["id"]), "dish_name": updated["dish_name"]}]
    else:
        # 叫全部 pending 菜品
        r = await db.execute(
            text("""
                UPDATE banquet_kds_dishes
                SET called_at    = :now,
                    serve_status = 'serving',
                    updated_at   = :now
                WHERE session_id = :sid::UUID
                  AND serve_status = 'pending'
                  AND is_deleted = FALSE
                RETURNING id, dish_name
            """),
            {"now": now, "sid": session_id},
        )
        called_dishes = [{"id": str(row["id"]), "dish_name": row["dish_name"]} for row in r.mappings().all()]

    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=KdsEventType.ORDER_READY,
            tenant_id=tenant_id,
            stream_id=session_id,
            payload={
                "session_id": session_id,
                "action": "call_kitchen",
                "dish_id": body.dish_id,
                "message": body.message,
                "called_dishes_count": len(called_dishes),
            },
            source_service="tx-trade",
        )
    )

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "called_dishes": called_dishes,
            "message": body.message,
        },
    }


# ─── 出品进度汇总 ────────────────────────────────────────────────────────────


@router.get("/{session_id}/progress", summary="出品进度汇总（已出N/总M）")
async def session_progress(
    session_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    sess_r = await db.execute(
        text("""
            SELECT id, contact_name, guest_count, table_count, status
            FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted = FALSE
        """),
        {"sid": session_id},
    )
    sess = sess_r.mappings().first()
    if not sess:
        raise HTTPException(status_code=404, detail="场次不存在")

    prog_r = await db.execute(
        text("""
            SELECT
                COUNT(*)                                            AS total_dishes,
                COUNT(*) FILTER (WHERE serve_status = 'served')    AS served_dishes,
                COUNT(*) FILTER (WHERE serve_status = 'serving')   AS serving_dishes,
                COUNT(*) FILTER (WHERE serve_status = 'pending')   AS pending_dishes,
                COALESCE(SUM(total_qty), 0)                        AS total_qty,
                COALESCE(SUM(served_qty), 0)                       AS served_qty
            FROM banquet_kds_dishes
            WHERE session_id = :sid::UUID AND is_deleted = FALSE
        """),
        {"sid": session_id},
    )
    prog = dict(prog_r.mappings().first())

    total = prog["total_dishes"] or 0
    served = prog["served_dishes"] or 0
    progress_pct = round(served / total * 100, 1) if total > 0 else 0.0

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "contact_name": sess["contact_name"],
            "guest_count": sess["guest_count"],
            "session_status": sess["status"],
            "total_dishes": total,
            "served_dishes": served,
            "serving_dishes": prog["serving_dishes"] or 0,
            "pending_dishes": prog["pending_dishes"] or 0,
            "total_qty": prog["total_qty"],
            "served_qty": prog["served_qty"],
            "progress_pct": progress_pct,
        },
    }
