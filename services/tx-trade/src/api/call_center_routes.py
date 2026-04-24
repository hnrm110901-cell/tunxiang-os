"""呼叫中心 API — 预订电话集成

9个端点：来电处理 / 挂断记录 / 通话历史 / 未接来电 /
         客户弹屏 / 创建回拨 / 回拨列表 / 完成回拨 / 通话统计
"""

from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.call_center_service import CallCenterService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["call-center"])

svc = CallCenterService()


# ── Request / Response Models ──

class IncomingCallReq(BaseModel):
    store_id: UUID
    caller_phone: str = Field(..., max_length=20)
    agent_ext: Optional[str] = Field(None, max_length=20)


class HangupReq(BaseModel):
    call_id: UUID
    duration_sec: int = Field(..., ge=0)
    recording_url: Optional[str] = None
    status: str = Field("answered", pattern="^(answered|missed|voicemail)$")


class CallbackCreateReq(BaseModel):
    store_id: UUID
    call_record_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    callback_phone: str = Field(..., max_length=20)
    reason: str = Field("custom", pattern="^(confirm_reservation|follow_up|missed_call|custom)$")
    assigned_to: Optional[UUID] = None
    scheduled_at: Optional[str] = None
    notes: Optional[str] = None


class CallbackCompleteReq(BaseModel):
    notes: Optional[str] = None


# ── Endpoints ──

@router.post("/api/v1/trade/calls/incoming")
async def incoming_call(
    body: IncomingCallReq,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """来电处理：创建通话记录 + 客户匹配 + 弹屏数据"""
    try:
        result = await svc.handle_incoming_call(
            db, x_tenant_id, body.store_id, body.caller_phone, body.agent_ext,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/v1/trade/calls/hangup")
async def hangup_call(
    body: HangupReq,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通话挂断：更新时长/录音/状态，未接自动创建回拨任务"""
    try:
        result = await svc.record_call_hangup(
            db, x_tenant_id, body.call_id, body.duration_sec,
            body.recording_url, body.status,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/v1/trade/calls/history")
async def call_history(
    store_id: UUID = Query(...),
    phone: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通话历史（分页）"""
    result = await svc.get_call_history(db, x_tenant_id, store_id, phone, page, size)
    return {"ok": True, "data": result}


@router.get("/api/v1/trade/calls/missed")
async def missed_calls(
    store_id: UUID = Query(...),
    date_str: Optional[str] = Query(None, alias="date"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """未接来电列表"""
    target_date = date.fromisoformat(date_str) if date_str else None
    result = await svc.get_missed_calls(db, x_tenant_id, store_id, target_date)
    return {"ok": True, "data": result}


@router.get("/api/v1/trade/calls/customer-popup/{phone}")
async def customer_popup(
    phone: str,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """客户弹屏：根据手机号查询客户画像 + RFM + 近期订单 + 预订"""
    result = await svc.get_customer_popup(db, x_tenant_id, phone)
    if result is None:
        return {"ok": True, "data": None, "error": {"message": "客户未找到"}}
    return {"ok": True, "data": result}


@router.post("/api/v1/trade/calls/callback")
async def create_callback(
    body: CallbackCreateReq,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建回拨任务"""
    try:
        result = await svc.create_callback_task(
            db, x_tenant_id, body.store_id, body.model_dump(),
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/v1/trade/calls/callback/tasks")
async def callback_tasks(
    store_id: UUID = Query(...),
    assigned_to: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """回拨任务列表"""
    result = await svc.get_callback_tasks(
        db, x_tenant_id, store_id, assigned_to, status,
    )
    return {"ok": True, "data": result}


@router.patch("/api/v1/trade/calls/callback/{task_id}/complete")
async def complete_callback(
    task_id: UUID,
    body: CallbackCompleteReq,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """完成回拨任务"""
    try:
        result = await svc.complete_callback(db, x_tenant_id, task_id, body.notes)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/v1/trade/calls/stats")
async def call_stats(
    store_id: UUID = Query(...),
    period: str = Query("today", pattern="^(today|week|month)$"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通话统计：接通率、未接率、平均通话时长"""
    result = await svc.get_call_stats(db, x_tenant_id, store_id, period)
    return {"ok": True, "data": result}
