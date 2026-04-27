"""服务呼叫 API — 催菜/呼叫服务员/需要物品/投诉/买单 (v149)

service_calls 表的 CRUD + 实时看板。
来源：POS端 / 消费者扫码自助呼叫 / 服务员App / KDS催菜

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import TableEventType
from shared.ontology.src.database import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/service-calls", tags=["service-calls"])

VALID_CALL_TYPES = {
    "call_waiter",  # 呼叫服务员
    "urge_dish",  # 催菜
    "need_item",  # 需要物品（纸巾/餐具/热水等）
    "complaint",  # 投诉
    "checkout_request",  # 买单请求（自助扫码场景）
    "other",  # 其他
}

VALID_STATUSES = {"pending", "handling", "handled", "cancelled"}


# ─── 工具 ─────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateServiceCallReq(BaseModel):
    """发起服务呼叫"""

    store_id: uuid.UUID
    table_session_id: uuid.UUID = Field(description="堂食会话ID（dining_sessions.id）")
    call_type: str = Field(description="呼叫类型")
    content: Optional[str] = Field(default=None, max_length=500, description="呼叫内容")
    target_dish_id: Optional[uuid.UUID] = None
    target_order_item_id: Optional[uuid.UUID] = None
    called_by: str = Field(default="pos", description="来源：pos/self_order/crew_app/kds")
    caller_name: Optional[str] = Field(default=None, max_length=50)

    @field_validator("call_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in VALID_CALL_TYPES:
            raise ValueError(f"call_type 必须是 {VALID_CALL_TYPES} 之一")
        return v

    @field_validator("called_by")
    @classmethod
    def _valid_source(cls, v: str) -> str:
        allowed = {"pos", "self_order", "crew_app", "kds"}
        if v not in allowed:
            raise ValueError(f"called_by 必须是 {allowed} 之一")
        return v


class HandleCallReq(BaseModel):
    """处理（响应）服务呼叫"""

    handled_by: uuid.UUID = Field(description="处理员工ID")


class BatchHandleReq(BaseModel):
    """批量处理多个呼叫（服务员清空待处理队列）"""

    call_ids: list[uuid.UUID]
    handled_by: uuid.UUID


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("", summary="发起服务呼叫")
async def create_service_call(
    body: CreateServiceCallReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    发起服务呼叫（催菜/呼叫服务员/需要物品等）。

    - POS端：收银员/服务员代客呼叫
    - 消费者端：扫码后自助呼叫
    - KDS端：厨师主动催单通知
    """
    tid = _get_tenant_id(request)
    now = _now_utc()
    call_id = uuid.uuid4()

    result = await db.execute(
        text("""
            INSERT INTO service_calls (
                id, tenant_id, store_id, table_session_id,
                call_type, content,
                target_dish_id, target_order_item_id,
                status, called_by, caller_name,
                called_at, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :session_id,
                :call_type, :content,
                :target_dish_id, :target_order_item_id,
                'pending', :called_by, :caller_name,
                :now, :now, :now
            )
            RETURNING *
        """),
        {
            "id": call_id,
            "tenant_id": tid,
            "store_id": body.store_id,
            "session_id": body.table_session_id,
            "call_type": body.call_type,
            "content": body.content,
            "target_dish_id": body.target_dish_id,
            "target_order_item_id": body.target_order_item_id,
            "called_by": body.called_by,
            "caller_name": body.caller_name,
            "now": now,
        },
    )
    call_row = dict(result.mappings().one())

    # 同步更新会话的 service_call_count
    await db.execute(
        text("""
            UPDATE dining_sessions
            SET service_call_count = service_call_count + 1,
                updated_at = :now
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {"now": now, "session_id": body.table_session_id, "tenant_id": tid},
    )

    # 写入会话事件流
    await db.execute(
        text("""
            INSERT INTO dining_session_events (
                id, tenant_id, store_id, table_session_id,
                event_type, payload, operator_type, occurred_at
            ) VALUES (
                gen_random_uuid(), :tenant_id, :store_id, :session_id,
                :event_type, :payload::jsonb, :op_type, NOW()
            )
        """),
        {
            "tenant_id": tid,
            "store_id": body.store_id,
            "session_id": body.table_session_id,
            "event_type": TableEventType.SERVICE_CALLED.value,
            "payload": __import__("json").dumps(
                {
                    "call_id": str(call_id),
                    "call_type": body.call_type,
                    "content": body.content,
                }
            ),
            "op_type": "customer" if body.called_by == "self_order" else "employee",
        },
    )

    # 旁路发送跨域事件
    asyncio.create_task(
        emit_event(
            event_type=TableEventType.SERVICE_CALLED,
            tenant_id=uuid.UUID(tid),
            stream_id=str(body.table_session_id),
            payload={
                "call_id": str(call_id),
                "call_type": body.call_type,
                "content": body.content,
                "called_by": body.called_by,
            },
            store_id=body.store_id,
            source_service="tx-trade",
        )
    )

    logger.info(
        "service_call_created",
        call_id=str(call_id),
        session_id=str(body.table_session_id),
        call_type=body.call_type,
        called_by=body.called_by,
        tenant_id=tid,
    )
    return _ok(call_row)


@router.get("/pending", summary="门店待处理呼叫看板")
async def get_pending_calls(
    store_id: uuid.UUID = Query(...),
    call_type: Optional[str] = Query(default=None, description="按类型过滤"),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    获取门店当前所有未处理的服务呼叫。

    服务员端和管理端实时看板使用。按呼叫时间升序排列（先到先服务）。
    """
    tid = _get_tenant_id(request)

    type_filter = ""
    params: dict = {"store_id": store_id, "tenant_id": tid}
    if call_type:
        type_filter = "AND sc.call_type = :call_type"
        params["call_type"] = call_type

    result = await db.execute(
        text(f"""
            SELECT
                sc.*,
                ds.session_no,
                ds.table_no_snapshot AS table_no,
                ds.guest_count
            FROM service_calls sc
            JOIN dining_sessions ds ON ds.id = sc.table_session_id
            WHERE sc.store_id   = :store_id
              AND sc.tenant_id  = :tenant_id
              AND sc.status     = 'pending'
              {type_filter}
            ORDER BY sc.called_at ASC
        """),
        params,
    )
    calls = [dict(r) for r in result.mappings().all()]
    return _ok({"calls": calls, "total": len(calls)})


@router.get("/session/{session_id}", summary="某会话的所有呼叫")
async def get_session_calls(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取某堂食会话的所有服务呼叫历史（含已处理）。"""
    tid = _get_tenant_id(request)
    result = await db.execute(
        text("""
            SELECT * FROM service_calls
            WHERE table_session_id = :session_id
              AND tenant_id        = :tenant_id
            ORDER BY called_at DESC
        """),
        {"session_id": session_id, "tenant_id": tid},
    )
    return _ok([dict(r) for r in result.mappings().all()])


@router.post("/{call_id}/handle", summary="处理服务呼叫")
async def handle_call(
    call_id: uuid.UUID,
    body: HandleCallReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    服务员确认已响应呼叫。

    自动计算响应时长（response_seconds），用于服务SLA统计。
    """
    tid = _get_tenant_id(request)
    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE service_calls
            SET status           = 'handled',
                handled_by       = :handled_by,
                handled_at       = :now,
                response_seconds = EXTRACT(EPOCH FROM (:now - called_at))::INT,
                updated_at       = :now
            WHERE id        = :call_id
              AND tenant_id = :tenant_id
              AND status    IN ('pending', 'handling')
            RETURNING *
        """),
        {"handled_by": body.handled_by, "now": now, "call_id": call_id, "tenant_id": tid},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _err("呼叫不存在或已处理", code=404)

    logger.info(
        "service_call_handled",
        call_id=str(call_id),
        handled_by=str(body.handled_by),
        tenant_id=tid,
    )
    return _ok(dict(row))


@router.post("/batch-handle", summary="批量处理呼叫")
async def batch_handle_calls(
    body: BatchHandleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量确认处理多个服务呼叫（服务员一键清空待处理队列）。"""
    tid = _get_tenant_id(request)
    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE service_calls
            SET status           = 'handled',
                handled_by       = :handled_by,
                handled_at       = :now,
                response_seconds = EXTRACT(EPOCH FROM (:now - called_at))::INT,
                updated_at       = :now
            WHERE id        = ANY(:call_ids)
              AND tenant_id = :tenant_id
              AND status    IN ('pending', 'handling')
            RETURNING id
        """),
        {
            "handled_by": body.handled_by,
            "now": now,
            "call_ids": body.call_ids,
            "tenant_id": tid,
        },
    )
    handled_ids = [str(r["id"]) for r in result.mappings().all()]

    logger.info(
        "service_calls_batch_handled",
        handled_count=len(handled_ids),
        handled_by=str(body.handled_by),
        tenant_id=tid,
    )
    return _ok({"handled_count": len(handled_ids), "handled_ids": handled_ids})


@router.post("/{call_id}/cancel", summary="取消服务呼叫")
async def cancel_call(
    call_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取消待处理的服务呼叫（顾客自助取消或服务员取消）。"""
    tid = _get_tenant_id(request)
    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE service_calls
            SET status = 'cancelled', updated_at = :now
            WHERE id = :call_id AND tenant_id = :tenant_id
              AND status = 'pending'
            RETURNING id
        """),
        {"now": now, "call_id": call_id, "tenant_id": tid},
    )
    if result.rowcount == 0:
        _err("呼叫不存在或已不在 pending 状态", code=404)

    return _ok({"cancelled": True})


@router.get("/stats/store", summary="门店服务SLA统计")
async def get_store_service_stats(
    store_id: uuid.UUID = Query(...),
    stat_date: Optional[str] = Query(default=None, description="统计日期 YYYY-MM-DD，默认今日"),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    门店当日服务呼叫 SLA 统计。

    包含：各类型呼叫次数、平均响应时长、超时率（>3分钟）等。
    用于管理端服务质量分析。
    """
    tid = _get_tenant_id(request)
    date_filter = "DATE(sc.called_at AT TIME ZONE 'UTC') = :stat_date"
    params: dict = {
        "store_id": store_id,
        "tenant_id": tid,
        "stat_date": stat_date or __import__("datetime").date.today().isoformat(),
    }

    result = await db.execute(
        text(f"""
            SELECT
                sc.call_type,
                COUNT(*)                                    AS total_calls,
                COUNT(*) FILTER (WHERE sc.status = 'handled') AS handled_calls,
                COUNT(*) FILTER (WHERE sc.status = 'pending') AS pending_calls,
                ROUND(AVG(sc.response_seconds) FILTER (WHERE sc.response_seconds IS NOT NULL), 1)
                                                            AS avg_response_seconds,
                COUNT(*) FILTER (WHERE sc.response_seconds > 180) AS over_sla_count
            FROM service_calls sc
            WHERE sc.store_id  = :store_id
              AND sc.tenant_id = :tenant_id
              AND {date_filter}
            GROUP BY sc.call_type
            ORDER BY total_calls DESC
        """),
        params,
    )
    stats = [dict(r) for r in result.mappings().all()]

    # 汇总行
    totals = {
        "total_calls": sum(r["total_calls"] for r in stats),
        "handled_calls": sum(r["handled_calls"] for r in stats),
        "pending_calls": sum(r["pending_calls"] for r in stats),
        "over_sla_count": sum(r["over_sla_count"] for r in stats),
    }

    return _ok({"by_type": stats, "totals": totals})
