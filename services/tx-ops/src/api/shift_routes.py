"""E1 班次交班 API 路由

端点:
  POST /api/v1/ops/shifts                    开始新班次
  POST /api/v1/ops/shifts/{id}/handover      发起交班
  POST /api/v1/ops/shifts/{id}/confirm       确认交班
  GET  /api/v1/ops/shifts                    查询班次列表
  GET  /api/v1/ops/shifts/{id}/summary       班次汇总

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/shifts", tags=["ops-shifts"])
log = structlog.get_logger(__name__)

_VALID_SHIFT_TYPES = {"morning", "afternoon", "evening", "night"}
_VALID_STATUSES = {"pending", "confirmed", "disputed"}

# ─── 内存存储（生产替换为 asyncpg）────────────────────────────────────────────
_shifts: Dict[str, Dict[str, Any]] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StartShiftRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    shift_date: date = Field(..., description="班次日期")
    shift_type: str = Field(..., description="morning/afternoon/evening/night")
    handover_by: str = Field(..., description="交班人UUID")


class HandoverRequest(BaseModel):
    received_by: str = Field(..., description="接班人UUID")
    cash_counted_fen: int = Field(..., ge=0, description="清点现金（分）")
    pos_cash_fen: int = Field(..., ge=0, description="POS应收现金（分）")
    device_checklist: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="设备检查清单 [{item, status, note}]",
    )
    notes: Optional[str] = None


class ConfirmHandoverRequest(BaseModel):
    received_by: str = Field(..., description="确认接班人UUID")
    disputed: bool = Field(False, description="是否有争议")
    dispute_reason: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("", status_code=201)
async def start_shift(
    body: StartShiftRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E1: 开始新班次记录。"""
    if body.shift_type not in _VALID_SHIFT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"shift_type 必须是 {_VALID_SHIFT_TYPES} 之一",
        )

    shift_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    record: Dict[str, Any] = {
        "id": shift_id,
        "tenant_id": x_tenant_id,
        "store_id": body.store_id,
        "shift_date": body.shift_date.isoformat(),
        "shift_type": body.shift_type,
        "start_time": now.isoformat(),
        "end_time": None,
        "handover_by": body.handover_by,
        "received_by": None,
        "cash_counted_fen": 0,
        "pos_cash_fen": 0,
        "cash_diff_fen": 0,
        "device_checklist": [],
        "notes": None,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    _shifts[shift_id] = record

    log.info("shift_started", shift_id=shift_id, store_id=body.store_id,
             shift_type=body.shift_type, tenant_id=x_tenant_id)
    return {"ok": True, "data": record}


@router.post("/{shift_id}/handover")
async def initiate_handover(
    shift_id: str,
    body: HandoverRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E1: 发起交班（填写现金盘点、设备检查）。"""
    shift = _shifts.get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="班次记录不存在")
    if shift["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该班次")
    if shift["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"班次当前状态 {shift['status']}，无法发起交班")

    cash_diff = body.cash_counted_fen - body.pos_cash_fen
    now = datetime.now(tz=timezone.utc)
    shift.update(
        received_by=body.received_by,
        cash_counted_fen=body.cash_counted_fen,
        pos_cash_fen=body.pos_cash_fen,
        cash_diff_fen=cash_diff,
        device_checklist=body.device_checklist,
        notes=body.notes,
        end_time=now.isoformat(),
        updated_at=now.isoformat(),
    )

    log.info("shift_handover_initiated", shift_id=shift_id,
             cash_diff_fen=cash_diff, tenant_id=x_tenant_id)
    return {"ok": True, "data": shift}


@router.post("/{shift_id}/confirm")
async def confirm_handover(
    shift_id: str,
    body: ConfirmHandoverRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E1: 确认或标记争议交班。"""
    shift = _shifts.get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="班次记录不存在")
    if shift["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该班次")
    if shift["status"] not in {"pending"}:
        raise HTTPException(status_code=409, detail=f"班次当前状态 {shift['status']}，无法再次确认")

    now = datetime.now(tz=timezone.utc)
    new_status = "disputed" if body.disputed else "confirmed"
    shift.update(
        received_by=body.received_by,
        status=new_status,
        updated_at=now.isoformat(),
    )
    if body.disputed and body.dispute_reason:
        existing_notes = shift.get("notes") or ""
        shift["notes"] = f"{existing_notes}\n[争议] {body.dispute_reason}".strip()

    log.info("shift_handover_confirmed", shift_id=shift_id,
             status=new_status, tenant_id=x_tenant_id)
    return {"ok": True, "data": shift}


@router.get("")
async def list_shifts(
    store_id: str = Query(..., description="门店ID"),
    shift_date: Optional[date] = Query(None, description="筛选日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E1: 查询班次列表。"""
    results = [
        s for s in _shifts.values()
        if s["tenant_id"] == x_tenant_id
        and s["store_id"] == store_id
        and (shift_date is None or s["shift_date"] == shift_date.isoformat())
        and not s.get("is_deleted", False)
    ]
    results.sort(key=lambda s: s["created_at"])
    return {"ok": True, "data": {"items": results, "total": len(results)}}


@router.get("/{shift_id}/summary")
async def get_shift_summary(
    shift_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E1: 班次汇总（含现金差额、设备状态、交班状态）。"""
    shift = _shifts.get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="班次记录不存在")
    if shift["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权查看该班次")

    device_checklist = shift.get("device_checklist") or []
    failed_devices = [d for d in device_checklist if d.get("status") == "fail"]

    summary = {
        "shift_id": shift_id,
        "store_id": shift["store_id"],
        "shift_date": shift["shift_date"],
        "shift_type": shift["shift_type"],
        "status": shift["status"],
        "handover_by": shift["handover_by"],
        "received_by": shift["received_by"],
        "cash_counted_fen": shift["cash_counted_fen"],
        "pos_cash_fen": shift["pos_cash_fen"],
        "cash_diff_fen": shift["cash_diff_fen"],
        "cash_balanced": shift["cash_diff_fen"] == 0,
        "device_total": len(device_checklist),
        "device_failed": len(failed_devices),
        "failed_devices": failed_devices,
        "start_time": shift["start_time"],
        "end_time": shift["end_time"],
    }
    return {"ok": True, "data": summary}
