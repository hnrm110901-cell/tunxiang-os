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

import json
from datetime import date
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/shifts", tags=["ops-shifts"])
log = structlog.get_logger(__name__)

_VALID_SHIFT_TYPES = {"morning", "afternoon", "evening", "night"}
_VALID_STATUSES = {"pending", "confirmed", "disputed"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


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
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E1: 开始新班次记录。"""
    if body.shift_type not in _VALID_SHIFT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"shift_type 必须是 {_VALID_SHIFT_TYPES} 之一",
        )
    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text("""
                INSERT INTO shift_records
                    (tenant_id, store_id, shift_date, shift_type, handover_by, status)
                VALUES
                    (:tenant_id, :store_id, :shift_date, :shift_type, :handover_by, 'pending')
                RETURNING id, tenant_id, store_id, shift_date, shift_type,
                          start_time, end_time, handover_by, received_by,
                          cash_counted_fen, pos_cash_fen, cash_diff_fen,
                          notes, status, disputed, dispute_reason,
                          created_at, updated_at, is_deleted
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "shift_date": body.shift_date.isoformat(),
                "shift_type": body.shift_type,
                "handover_by": body.handover_by,
            },
        )
        row = result.mappings().one()
        await db.commit()
        record = dict(row)
        # serialize non-JSON-native types
        for k, v in record.items():
            if hasattr(v, "isoformat"):
                record[k] = v.isoformat()
        log.info("shift_started", shift_id=str(record["id"]), store_id=body.store_id,
                 shift_type=body.shift_type, tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("shift_start_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，开班失败")


@router.post("/{shift_id}/handover")
async def initiate_handover(
    shift_id: str,
    body: HandoverRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E1: 发起交班（填写现金盘点、设备检查）。"""
    try:
        await _set_tenant(db, x_tenant_id)
        check = await db.execute(
            text("SELECT id FROM shift_records WHERE id = :sid AND is_deleted = FALSE"),
            {"sid": shift_id},
        )
        if check.first() is None:
            raise HTTPException(status_code=404, detail="班次记录不存在")

        cash_diff_fen = body.cash_counted_fen - body.pos_cash_fen

        result = await db.execute(
            text("""
                UPDATE shift_records
                SET end_time         = NOW(),
                    received_by      = :received_by,
                    cash_counted_fen = :cash_counted_fen,
                    pos_cash_fen     = :pos_cash_fen,
                    cash_diff_fen    = :cash_diff_fen,
                    notes            = :notes,
                    updated_at       = NOW()
                WHERE id = :sid
                RETURNING id, tenant_id, store_id, shift_date, shift_type,
                          start_time, end_time, handover_by, received_by,
                          cash_counted_fen, pos_cash_fen, cash_diff_fen,
                          notes, status, disputed, dispute_reason,
                          created_at, updated_at, is_deleted
            """),
            {
                "sid": shift_id,
                "received_by": body.received_by,
                "cash_counted_fen": body.cash_counted_fen,
                "pos_cash_fen": body.pos_cash_fen,
                "cash_diff_fen": cash_diff_fen,
                "notes": body.notes,
            },
        )
        row = result.mappings().one()
        record = dict(row)

        # 清除旧设备检查数据
        await db.execute(
            text("DELETE FROM shift_device_checklist WHERE shift_id = :sid"),
            {"sid": shift_id},
        )

        # 批量插入新设备检查数据
        if body.device_checklist:
            for item in body.device_checklist:
                await db.execute(
                    text("""
                        INSERT INTO shift_device_checklist
                            (shift_id, tenant_id, item, status, note)
                        VALUES
                            (:shift_id, :tenant_id, :item, :status, :note)
                    """),
                    {
                        "shift_id": shift_id,
                        "tenant_id": x_tenant_id,
                        "item": item.get("item", ""),
                        "status": item.get("status", "ok"),
                        "note": item.get("note"),
                    },
                )

        await db.commit()

        for k, v in record.items():
            if hasattr(v, "isoformat"):
                record[k] = v.isoformat()

        log.info("shift_handover_initiated", shift_id=shift_id,
                 cash_diff_fen=cash_diff_fen, tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("shift_handover_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，交班失败")


@router.post("/{shift_id}/confirm")
async def confirm_handover(
    shift_id: str,
    body: ConfirmHandoverRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E1: 确认或标记争议交班。"""
    try:
        await _set_tenant(db, x_tenant_id)
        check = await db.execute(
            text("SELECT id FROM shift_records WHERE id = :sid AND is_deleted = FALSE"),
            {"sid": shift_id},
        )
        if check.first() is None:
            raise HTTPException(status_code=404, detail="班次记录不存在")

        new_status = "disputed" if body.disputed else "confirmed"
        result = await db.execute(
            text("""
                UPDATE shift_records
                SET status         = :status,
                    disputed       = :disputed,
                    dispute_reason = :dispute_reason,
                    received_by    = :received_by,
                    notes          = COALESCE(notes, '') || :appended_note,
                    updated_at     = NOW()
                WHERE id = :sid
                RETURNING id, tenant_id, store_id, shift_date, shift_type,
                          start_time, end_time, handover_by, received_by,
                          cash_counted_fen, pos_cash_fen, cash_diff_fen,
                          notes, status, disputed, dispute_reason,
                          created_at, updated_at, is_deleted
            """),
            {
                "sid": shift_id,
                "status": new_status,
                "disputed": body.disputed,
                "dispute_reason": body.dispute_reason,
                "received_by": body.received_by,
                "appended_note": (
                    f"\n[争议] {body.dispute_reason}"
                    if body.disputed and body.dispute_reason
                    else ""
                ),
            },
        )
        row = result.mappings().one()
        record = dict(row)
        await db.commit()

        for k, v in record.items():
            if hasattr(v, "isoformat"):
                record[k] = v.isoformat()

        log.info("shift_handover_confirmed", shift_id=shift_id,
                 status=new_status, tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("shift_confirm_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，确认交班失败")


@router.get("")
async def list_shifts(
    store_id: str = Query(..., description="门店ID"),
    shift_date: Optional[date] = Query(None, description="筛选日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E1: 查询班次列表。"""
    try:
        await _set_tenant(db, x_tenant_id)
        if shift_date is not None:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, store_id, shift_date, shift_type,
                           start_time, end_time, handover_by, received_by,
                           cash_counted_fen, pos_cash_fen, cash_diff_fen,
                           notes, status, disputed, dispute_reason,
                           created_at, updated_at, is_deleted
                    FROM shift_records
                    WHERE is_deleted = FALSE
                      AND store_id = :store_id
                      AND shift_date = :shift_date
                    ORDER BY shift_date DESC, created_at DESC
                    LIMIT 50
                """),
                {"store_id": store_id, "shift_date": shift_date.isoformat()},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, store_id, shift_date, shift_type,
                           start_time, end_time, handover_by, received_by,
                           cash_counted_fen, pos_cash_fen, cash_diff_fen,
                           notes, status, disputed, dispute_reason,
                           created_at, updated_at, is_deleted
                    FROM shift_records
                    WHERE is_deleted = FALSE
                      AND store_id = :store_id
                    ORDER BY shift_date DESC, created_at DESC
                    LIMIT 50
                """),
                {"store_id": store_id},
            )
        rows = result.mappings().all()
        items = []
        for row in rows:
            record = dict(row)
            for k, v in record.items():
                if hasattr(v, "isoformat"):
                    record[k] = v.isoformat()
            items.append(record)
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("shift_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，查询失败")


@router.get("/{shift_id}/summary")
async def get_shift_summary(
    shift_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E1: 班次汇总（含现金差额、设备状态、交班状态）。"""
    try:
        await _set_tenant(db, x_tenant_id)
        shift_result = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, shift_date, shift_type,
                       start_time, end_time, handover_by, received_by,
                       cash_counted_fen, pos_cash_fen, cash_diff_fen,
                       notes, status, disputed, dispute_reason,
                       created_at, updated_at, is_deleted
                FROM shift_records
                WHERE id = :sid
            """),
            {"sid": shift_id},
        )
        shift_row = shift_result.mappings().first()
        if shift_row is None:
            raise HTTPException(status_code=404, detail="班次记录不存在")
        shift = dict(shift_row)

        checklist_result = await db.execute(
            text("""
                SELECT id, shift_id, tenant_id, item, status, note, created_at
                FROM shift_device_checklist
                WHERE shift_id = :sid
            """),
            {"sid": shift_id},
        )
        device_checklist = [dict(r) for r in checklist_result.mappings().all()]

        failed_devices = [d for d in device_checklist if d.get("status") == "failed"]

        def _iso(v: Any) -> Any:
            return v.isoformat() if hasattr(v, "isoformat") else v

        summary = {
            "shift_id": str(shift["id"]),
            "store_id": str(shift["store_id"]),
            "shift_date": _iso(shift["shift_date"]),
            "shift_type": shift["shift_type"],
            "status": shift["status"],
            "handover_by": str(shift["handover_by"]),
            "received_by": str(shift["received_by"]) if shift["received_by"] else None,
            "cash_counted_fen": shift["cash_counted_fen"],
            "pos_cash_fen": shift["pos_cash_fen"],
            "cash_diff_fen": shift["cash_diff_fen"],
            "cash_balanced": shift["cash_diff_fen"] == 0,
            "device_total": len(device_checklist),
            "device_failed": len(failed_devices),
            "failed_devices": [
                {k: _iso(v) for k, v in d.items()} for d in failed_devices
            ],
            "start_time": _iso(shift["start_time"]),
            "end_time": _iso(shift["end_time"]),
        }
        return {"ok": True, "data": summary}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("shift_summary_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，查询汇总失败")
