"""服务铃 API 路由"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.service_bell_service import (
    create_call,
    respond_call,
    get_pending_calls,
    get_call_history,
)

router = APIRouter(prefix="/api/v1/service-bell", tags=["service-bell"])

CALL_TYPES = {"add_dish", "checkout", "paper", "water", "other"}


class CreateCallRequest(BaseModel):
    store_id: str
    table_no: str
    call_type: str
    call_type_label: Optional[str] = None


class RespondCallRequest(BaseModel):
    operator_id: str


def _serialize_call(call) -> dict:
    return {
        "call_id": str(call.id),
        "store_id": str(call.store_id),
        "table_no": call.table_no,
        "call_type": call.call_type,
        "call_type_label": call.call_type_label,
        "status": call.status,
        "operator_id": str(call.operator_id) if call.operator_id else None,
        "called_at": call.called_at.isoformat(),
        "responded_at": call.responded_at.isoformat() if call.responded_at else None,
    }


@router.post("")
async def api_create_call(
    body: CreateCallRequest,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """顾客扫码呼叫服务（公开接口，无需认证）。"""
    if body.call_type not in CALL_TYPES:
        raise HTTPException(status_code=400, detail=f"call_type must be one of {sorted(CALL_TYPES)}")
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        call = await create_call(
            store_id=body.store_id,
            table_no=body.table_no,
            call_type=body.call_type,
            call_type_label=body.call_type_label,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": _serialize_call(call)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{call_id}/respond")
async def api_respond_call(
    call_id: str,
    body: RespondCallRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """服务员响应呼叫。"""
    try:
        call = await respond_call(
            call_id=call_id,
            operator_id=body.operator_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": _serialize_call(call)}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/pending")
async def api_get_pending(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """服务员App启动时拉取当前待响应列表。"""
    calls = await get_pending_calls(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": {"items": [_serialize_call(c) for c in calls], "total": len(calls)}}


@router.get("/history")
async def api_get_history(
    store_id: str = Query(...),
    date: date = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """历史记录查询。"""
    calls = await get_call_history(
        store_id=store_id,
        query_date=date,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": {"items": [_serialize_call(c) for c in calls], "total": len(calls)}}
