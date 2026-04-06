"""统一排班中心 API 路由（基于 unified_schedules 新表）

端点列表（prefix=/api/v1/schedules）：

排班 CRUD：
  GET    /api/v1/schedules/week                          周排班视图（按员工分组，返回7天排班矩阵）
  POST   /api/v1/schedules                               创建单条排班
  POST   /api/v1/schedules/batch                         批量创建（按模板+员工列表+日期范围）
  PUT    /api/v1/schedules/{schedule_id}                 修改排班
  DELETE /api/v1/schedules/{schedule_id}                 取消排班（设 status=cancelled）
  GET    /api/v1/schedules/employee/{employee_id}/week   某员工周排班

冲突检测：
  GET    /api/v1/schedules/conflicts                     检测时间冲突
  POST   /api/v1/schedules/validate                      创建前预校验

调班换班：
  POST   /api/v1/schedules/swap                          发起调班申请
  GET    /api/v1/schedules/swap-requests                 调班申请列表
  POST   /api/v1/schedules/swap-requests/{request_id}/approve  审批调班
  POST   /api/v1/schedules/swap-requests/{request_id}/reject   拒绝调班

缺口管理：
  GET    /api/v1/schedules/gaps                          缺口班次列表
  POST   /api/v1/schedules/gaps                          创建缺口（手动标记）
  POST   /api/v1/schedules/gaps/{gap_id}/claim           员工认领缺口
  POST   /api/v1/schedules/gaps/{gap_id}/fill            店长指派填补
  POST   /api/v1/schedules/gaps/auto-detect              自动检测缺口

班次模板：
  GET    /api/v1/schedules/templates                     班次模板列表
  POST   /api/v1/schedules/templates                     创建模板
  PUT    /api/v1/schedules/templates/{template_id}       更新模板
  DELETE /api/v1/schedules/templates/{template_id}       删除模板

统计：
  GET    /api/v1/schedules/statistics                    排班统计

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.org_events import OrgEventType
from shared.events.src.emitter import emit_event
from shared.ontology.src.database import get_db

from ..services.unified_schedule_service import (
    auto_detect_gaps,
    batch_create_schedules,
    create_schedule as svc_create_schedule,
    detect_conflicts,
    get_fill_suggestions,
    get_week_schedule,
    swap_schedules,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/schedules", tags=["unified-schedules"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateScheduleReq(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    store_id: str = Field(..., description="门店 ID")
    schedule_date: date = Field(..., description="排班日期 YYYY-MM-DD")
    shift_start: str = Field(..., description="班次开始时间 HH:MM")
    shift_end: str = Field(..., description="班次结束时间 HH:MM")
    template_id: Optional[str] = Field(None, description="班次模板 ID")
    role: Optional[str] = Field(None, description="排班岗位")
    notes: Optional[str] = Field(None, description="备注")


class BatchCreateReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    template_id: str = Field(..., description="班次模板 ID")
    employee_ids: list[str] = Field(..., description="员工 ID 列表")
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")


class UpdateScheduleReq(BaseModel):
    shift_start: Optional[str] = Field(None, description="新班次开始时间 HH:MM")
    shift_end: Optional[str] = Field(None, description="新班次结束时间 HH:MM")
    employee_id: Optional[str] = Field(None, description="换人：新员工 ID")
    template_id: Optional[str] = Field(None, description="班次模板 ID")
    status: Optional[str] = Field(None, description="状态：scheduled/confirmed/cancelled")
    role: Optional[str] = Field(None, description="岗位")
    notes: Optional[str] = Field(None, description="备注")


class ValidateScheduleReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    schedules: list[CreateScheduleReq] = Field(..., description="待校验的排班列表")


class SwapRequestReq(BaseModel):
    from_schedule_id: str = Field(..., description="原排班 ID")
    to_employee_id: str = Field(..., description="目标员工 ID")
    reason: Optional[str] = Field(None, description="调班原因")


class RejectSwapReq(BaseModel):
    reason: Optional[str] = Field(None, description="拒绝原因")


class CreateGapReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    gap_date: date = Field(..., description="缺口日期")
    shift_start: str = Field(..., description="缺口开始时间 HH:MM")
    shift_end: str = Field(..., description="缺口结束时间 HH:MM")
    role: str = Field(..., description="缺口岗位")
    reason: Optional[str] = Field(None, description="缺口原因")


class FillGapReq(BaseModel):
    employee_id: str = Field(..., description="指派填补的员工 ID")


class CreateTemplateReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    name: str = Field(..., description="模板名称，如早班/中班/晚班")
    shift_start: str = Field(..., description="班次开始时间 HH:MM")
    shift_end: str = Field(..., description="班次结束时间 HH:MM")
    break_minutes: int = Field(0, ge=0, description="休息时长（分钟）")
    color: Optional[str] = Field(None, description="模板颜色标识，如 #FF6B35")
    description: Optional[str] = Field(None, description="模板说明")


class UpdateTemplateReq(BaseModel):
    name: Optional[str] = Field(None, description="模板名称")
    shift_start: Optional[str] = Field(None, description="班次开始时间 HH:MM")
    shift_end: Optional[str] = Field(None, description="班次结束时间 HH:MM")
    break_minutes: Optional[int] = Field(None, ge=0, description="休息时长（分钟）")
    color: Optional[str] = Field(None, description="颜色标识")
    description: Optional[str] = Field(None, description="模板说明")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  排班 CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/week")
async def api_get_week_schedule(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    start_date: date = Query(..., description="周起始日 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/week - 周排班视图（按员工分组，返回7天排班矩阵）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    data = await get_week_schedule(db, tenant_id, store_id, start_date)

    log.info("week_schedule_queried", store_id=store_id, start_date=str(start_date), tenant_id=tenant_id)
    return _ok(data)


@router.post("")
async def api_create_schedule(
    req: CreateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules - 创建单条排班"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await svc_create_schedule(db, tenant_id, req.model_dump())

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SCHEDULE_CREATED,
        tenant_id=UUID(tenant_id),
        stream_id=result["schedule_id"],
        payload={
            "employee_id": req.employee_id,
            "store_id": req.store_id,
            "schedule_date": req.schedule_date.isoformat(),
            "shift_start": req.shift_start,
            "shift_end": req.shift_end,
        },
        store_id=UUID(req.store_id) if req.store_id else None,
        source_service="tx-org",
    ))

    log.info("schedule_created", employee_id=req.employee_id, store_id=req.store_id, tenant_id=tenant_id)
    return _ok(result)


@router.post("/batch")
async def api_batch_create_schedules(
    req: BatchCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/batch - 批量创建（按模板+员工列表+日期范围）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await batch_create_schedules(
        db, tenant_id, req.template_id, req.employee_ids, req.start_date, req.end_date,
    )

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SCHEDULE_BATCH_CREATED,
        tenant_id=UUID(tenant_id),
        stream_id=req.store_id,
        payload={
            "store_id": req.store_id,
            "template_id": req.template_id,
            "employee_count": len(req.employee_ids),
            "inserted": result["inserted"],
            "skipped": result["skipped_conflicts"],
        },
        store_id=UUID(req.store_id) if req.store_id else None,
        source_service="tx-org",
    ))

    log.info(
        "schedules_batch_created",
        store_id=req.store_id,
        inserted=result["inserted"],
        skipped=result["skipped_conflicts"],
        tenant_id=tenant_id,
    )
    return _ok(result)


@router.put("/{schedule_id}")
async def api_update_schedule(
    schedule_id: str,
    req: UpdateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PUT /api/v1/schedules/{schedule_id} - 修改排班"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.status and req.status not in ("scheduled", "confirmed", "cancelled"):
        raise HTTPException(status_code=400, detail="status 须为 scheduled / confirmed / cancelled")

    changes = {k: v for k, v in req.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(status_code=400, detail="未提供任何需要更新的字段")

    # 构造动态 SET 子句
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"schedule_id": schedule_id, "tid": tenant_id}

    field_map = {
        "shift_start": "shift_start = :shift_start::time",
        "shift_end": "shift_end = :shift_end::time",
        "employee_id": "employee_id = :new_employee_id",
        "template_id": "template_id = :template_id",
        "status": "status = :status",
        "role": "role = :role",
        "notes": "notes = :notes",
    }
    for field_name, sql_expr in field_map.items():
        val = getattr(req, field_name, None)
        if val is not None:
            set_parts.append(sql_expr)
            param_key = "new_employee_id" if field_name == "employee_id" else field_name
            params[param_key] = val

    set_clause = ", ".join(set_parts)

    result = await db.execute(
        text(
            f"UPDATE unified_schedules SET {set_clause} "
            "WHERE id = :schedule_id::uuid AND tenant_id = :tid::uuid "
            "AND is_deleted = FALSE "
            "RETURNING id, employee_id, store_id, schedule_date, "
            "shift_start::text, shift_end::text, status, role, notes"
        ),
        params,
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="排班记录不存在")

    row_data = dict(row)

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SCHEDULE_UPDATED,
        tenant_id=UUID(tenant_id),
        stream_id=schedule_id,
        payload={"schedule_id": schedule_id, "changes": changes},
        store_id=UUID(str(row_data["store_id"])),
        source_service="tx-org",
    ))

    log.info("schedule_updated", schedule_id=schedule_id, changes=changes, tenant_id=tenant_id)
    return _ok({
        "schedule_id": str(row_data["id"]),
        "employee_id": str(row_data["employee_id"]),
        "schedule_date": row_data["schedule_date"].isoformat() if hasattr(row_data["schedule_date"], "isoformat") else str(row_data["schedule_date"]),
        "shift_start": str(row_data["shift_start"]),
        "shift_end": str(row_data["shift_end"]),
        "status": row_data["status"],
        "role": row_data.get("role"),
        "notes": row_data.get("notes"),
    })


@router.delete("/{schedule_id}")
async def api_delete_schedule(
    schedule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """DELETE /api/v1/schedules/{schedule_id} - 取消排班（设 status=cancelled）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            "UPDATE unified_schedules "
            "SET status = 'cancelled', is_deleted = TRUE, updated_at = NOW() "
            "WHERE id = :schedule_id::uuid AND tenant_id = :tid::uuid "
            "AND is_deleted = FALSE "
            "RETURNING id, employee_id, store_id, schedule_date"
        ),
        {"schedule_id": schedule_id, "tid": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="排班记录不存在或已取消")

    row_data = dict(row)

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SCHEDULE_CANCELLED,
        tenant_id=UUID(tenant_id),
        stream_id=schedule_id,
        payload={"schedule_id": schedule_id, "employee_id": str(row_data["employee_id"])},
        store_id=UUID(str(row_data["store_id"])),
        source_service="tx-org",
    ))

    log.info("schedule_cancelled", schedule_id=schedule_id, tenant_id=tenant_id)
    return _ok({
        "schedule_id": str(row_data["id"]),
        "employee_id": str(row_data["employee_id"]),
        "schedule_date": row_data["schedule_date"].isoformat() if hasattr(row_data["schedule_date"], "isoformat") else str(row_data["schedule_date"]),
        "status": "cancelled",
    })


@router.get("/employee/{employee_id}/week")
async def api_get_employee_week(
    employee_id: str,
    request: Request,
    start_date: date = Query(..., description="周起始日 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/employee/{employee_id}/week - 某员工周排班"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    end_date = start_date + timedelta(days=6)
    result = await db.execute(
        text(
            "SELECT us.id, us.schedule_date, us.shift_start::text, us.shift_end::text, "
            "us.status, us.role, us.notes, us.store_id, "
            "st.name AS template_name "
            "FROM unified_schedules us "
            "LEFT JOIN shift_templates st ON st.id = us.template_id AND st.tenant_id = us.tenant_id "
            "WHERE us.tenant_id = :tid::uuid "
            "AND us.employee_id = :eid::uuid "
            "AND us.schedule_date BETWEEN :start AND :end "
            "AND us.is_deleted = FALSE "
            "ORDER BY us.schedule_date, us.shift_start"
        ),
        {"tid": tenant_id, "eid": employee_id, "start": start_date, "end": end_date},
    )
    rows = [dict(r) for r in result.mappings().fetchall()]

    shifts = [
        {
            "schedule_id": str(row["id"]),
            "date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
            "shift_start": str(row["shift_start"]),
            "shift_end": str(row["shift_end"]),
            "status": row["status"],
            "role": row.get("role"),
            "template_name": row.get("template_name"),
            "store_id": str(row["store_id"]),
            "notes": row.get("notes"),
        }
        for row in rows
    ]

    log.info("employee_week_queried", employee_id=employee_id, start_date=str(start_date), tenant_id=tenant_id)
    return _ok({
        "employee_id": employee_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "shifts": shifts,
        "total_shifts": len(shifts),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  冲突检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/conflicts")
async def api_get_conflicts(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/conflicts - 检测时间冲突"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conflicts = await detect_conflicts(db, tenant_id, store_id, start_date, end_date)

    log.info("conflicts_checked", store_id=store_id, conflict_count=len(conflicts), tenant_id=tenant_id)
    return _ok({
        "store_id": store_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "has_conflicts": len(conflicts) > 0,
    })


@router.post("/validate")
async def api_validate_schedules(
    req: ValidateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/validate - 创建前预校验（返回冲突列表）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 收集所有日期范围
    if not req.schedules:
        return _ok({"conflicts": [], "conflict_count": 0, "is_valid": True})

    dates = [s.schedule_date for s in req.schedules]
    min_date, max_date = min(dates), max(dates)

    # 获取已有排班的冲突
    existing_conflicts = await detect_conflicts(db, tenant_id, req.store_id, min_date, max_date)

    # 检测待创建排班之间的内部冲突
    internal_conflicts: list[dict[str, Any]] = []
    for i, a in enumerate(req.schedules):
        for b in req.schedules[i + 1:]:
            if (
                a.employee_id == b.employee_id
                and a.schedule_date == b.schedule_date
                and a.shift_start < b.shift_end
                and a.shift_end > b.shift_start
            ):
                internal_conflicts.append({
                    "employee_id": a.employee_id,
                    "date": a.schedule_date.isoformat(),
                    "type": "internal",
                    "shift_a": {"start": a.shift_start, "end": a.shift_end},
                    "shift_b": {"start": b.shift_start, "end": b.shift_end},
                })

    # 检测待创建排班与已有排班的冲突
    cross_conflicts: list[dict[str, Any]] = []
    for s in req.schedules:
        check_result = await db.execute(
            text(
                "SELECT id, shift_start::text, shift_end::text "
                "FROM unified_schedules "
                "WHERE tenant_id = :tid::uuid AND employee_id = :eid::uuid "
                "AND schedule_date = :d AND is_deleted = FALSE "
                "AND status != 'cancelled' "
                "AND shift_start < :new_end::time AND shift_end > :new_start::time"
            ),
            {
                "tid": tenant_id, "eid": s.employee_id,
                "d": s.schedule_date, "new_start": s.shift_start, "new_end": s.shift_end,
            },
        )
        for row in check_result.mappings().fetchall():
            cross_conflicts.append({
                "employee_id": s.employee_id,
                "date": s.schedule_date.isoformat(),
                "type": "cross_existing",
                "new_shift": {"start": s.shift_start, "end": s.shift_end},
                "existing_schedule_id": str(row["id"]),
                "existing_shift": {"start": str(row["shift_start"]), "end": str(row["shift_end"])},
            })

    all_conflicts = existing_conflicts + internal_conflicts + cross_conflicts

    log.info("schedules_validated", store_id=req.store_id, conflict_count=len(all_conflicts), tenant_id=tenant_id)
    return _ok({
        "conflicts": all_conflicts,
        "conflict_count": len(all_conflicts),
        "is_valid": len(all_conflicts) == 0,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  调班换班
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/swap")
async def api_swap_request(
    req: SwapRequestReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/swap - 发起调班申请"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 查找原排班
    orig = await db.execute(
        text(
            "SELECT id, employee_id, store_id, schedule_date, shift_start::text, shift_end::text "
            "FROM unified_schedules "
            "WHERE id = :sid::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE"
        ),
        {"sid": req.from_schedule_id, "tid": tenant_id},
    )
    orig_row = orig.mappings().first()
    if orig_row is None:
        raise HTTPException(status_code=404, detail="原排班记录不存在")

    orig_data = dict(orig_row)

    # 创建调班申请记录
    result = await db.execute(
        text(
            "INSERT INTO schedule_swap_requests "
            "(tenant_id, store_id, from_schedule_id, from_employee_id, to_employee_id, "
            "reason, status) "
            "VALUES (:tid::uuid, :store_id::uuid, :from_sid::uuid, :from_eid::uuid, "
            ":to_eid::uuid, :reason, 'pending') "
            "RETURNING id, created_at"
        ),
        {
            "tid": tenant_id,
            "store_id": str(orig_data["store_id"]),
            "from_sid": req.from_schedule_id,
            "from_eid": str(orig_data["employee_id"]),
            "to_eid": req.to_employee_id,
            "reason": req.reason,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="创建调班申请失败")

    row_data = dict(row)

    log.info(
        "swap_request_created",
        request_id=str(row_data["id"]),
        from_schedule=req.from_schedule_id,
        to_employee=req.to_employee_id,
        tenant_id=tenant_id,
    )
    return _ok({
        "request_id": str(row_data["id"]),
        "from_schedule_id": req.from_schedule_id,
        "from_employee_id": str(orig_data["employee_id"]),
        "to_employee_id": req.to_employee_id,
        "status": "pending",
        "reason": req.reason,
        "created_at": str(row_data["created_at"]),
    })


@router.get("/swap-requests")
async def api_get_swap_requests(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    status: Optional[str] = Query(None, description="筛选状态: pending/approved/rejected"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/swap-requests - 调班申请列表"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = (
        "SELECT sr.id, sr.from_schedule_id, sr.from_employee_id, sr.to_employee_id, "
        "sr.reason, sr.status, sr.created_at, sr.reviewed_at, sr.reviewer_notes, "
        "e1.name AS from_employee_name, e2.name AS to_employee_name, "
        "us.schedule_date, us.shift_start::text, us.shift_end::text "
        "FROM schedule_swap_requests sr "
        "LEFT JOIN employees e1 ON e1.id = sr.from_employee_id AND e1.tenant_id = sr.tenant_id "
        "LEFT JOIN employees e2 ON e2.id = sr.to_employee_id AND e2.tenant_id = sr.tenant_id "
        "LEFT JOIN unified_schedules us ON us.id = sr.from_schedule_id AND us.tenant_id = sr.tenant_id "
        "WHERE sr.tenant_id = :tid::uuid AND sr.store_id = :store_id::uuid "
    )
    params: dict[str, Any] = {"tid": tenant_id, "store_id": store_id}

    if status:
        sql += "AND sr.status = :status "
        params["status"] = status

    sql += "ORDER BY sr.created_at DESC"

    result = await db.execute(text(sql), params)
    rows = [dict(r) for r in result.mappings().fetchall()]

    items = [
        {
            "request_id": str(row["id"]),
            "from_schedule_id": str(row["from_schedule_id"]),
            "from_employee_id": str(row["from_employee_id"]),
            "from_employee_name": row.get("from_employee_name"),
            "to_employee_id": str(row["to_employee_id"]),
            "to_employee_name": row.get("to_employee_name"),
            "schedule_date": row["schedule_date"].isoformat() if row.get("schedule_date") and hasattr(row["schedule_date"], "isoformat") else str(row.get("schedule_date", "")),
            "shift_start": str(row.get("shift_start", "")),
            "shift_end": str(row.get("shift_end", "")),
            "reason": row.get("reason"),
            "status": row["status"],
            "reviewer_notes": row.get("reviewer_notes"),
            "created_at": str(row["created_at"]),
            "reviewed_at": str(row["reviewed_at"]) if row.get("reviewed_at") else None,
        }
        for row in rows
    ]

    log.info("swap_requests_listed", store_id=store_id, count=len(items), tenant_id=tenant_id)
    return _ok({"items": items, "total": len(items)})


@router.post("/swap-requests/{request_id}/approve")
async def api_approve_swap(
    request_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/swap-requests/{request_id}/approve - 审批调班"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 获取调班申请
    sr = await db.execute(
        text(
            "SELECT id, from_schedule_id, from_employee_id, to_employee_id, store_id "
            "FROM schedule_swap_requests "
            "WHERE id = :rid::uuid AND tenant_id = :tid::uuid AND status = 'pending'"
        ),
        {"rid": request_id, "tid": tenant_id},
    )
    sr_row = sr.mappings().first()
    if sr_row is None:
        raise HTTPException(status_code=404, detail="调班申请不存在或已处理")

    sr_data = dict(sr_row)

    # 执行调班：更新原排班的 employee_id
    swap_result = await swap_schedules(
        db, tenant_id, str(sr_data["from_schedule_id"]), str(sr_data["to_employee_id"]),
    )

    # 更新申请状态
    await db.execute(
        text(
            "UPDATE schedule_swap_requests "
            "SET status = 'approved', reviewed_at = NOW() "
            "WHERE id = :rid::uuid"
        ),
        {"rid": request_id},
    )

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SCHEDULE_SWAPPED,
        tenant_id=UUID(tenant_id),
        stream_id=str(sr_data["from_schedule_id"]),
        payload={
            "request_id": request_id,
            "from_employee_id": str(sr_data["from_employee_id"]),
            "to_employee_id": str(sr_data["to_employee_id"]),
        },
        store_id=UUID(str(sr_data["store_id"])),
        source_service="tx-org",
    ))

    log.info("swap_approved", request_id=request_id, tenant_id=tenant_id)
    return _ok({"request_id": request_id, "status": "approved", **swap_result})


@router.post("/swap-requests/{request_id}/reject")
async def api_reject_swap(
    request_id: str,
    req: RejectSwapReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/swap-requests/{request_id}/reject - 拒绝调班"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            "UPDATE schedule_swap_requests "
            "SET status = 'rejected', reviewed_at = NOW(), reviewer_notes = :notes "
            "WHERE id = :rid::uuid AND tenant_id = :tid::uuid AND status = 'pending' "
            "RETURNING id"
        ),
        {"rid": request_id, "tid": tenant_id, "notes": req.reason},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="调班申请不存在或已处理")

    log.info("swap_rejected", request_id=request_id, tenant_id=tenant_id)
    return _ok({"request_id": request_id, "status": "rejected", "reason": req.reason})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  缺口管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/gaps")
async def api_get_gaps(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    gap_date: Optional[date] = Query(None, description="指定日期筛选"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/gaps - 缺口班次列表"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = (
        "SELECT sg.id, sg.store_id, sg.gap_date, sg.shift_start::text, sg.shift_end::text, "
        "sg.role, sg.status, sg.reason, sg.claimed_by, sg.filled_by, sg.created_at, "
        "e.name AS claimed_by_name "
        "FROM shift_gaps sg "
        "LEFT JOIN employees e ON e.id = sg.claimed_by AND e.tenant_id = sg.tenant_id "
        "WHERE sg.tenant_id = :tid::uuid AND sg.store_id = :store_id::uuid "
        "AND sg.is_deleted = FALSE "
    )
    params: dict[str, Any] = {"tid": tenant_id, "store_id": store_id}

    if gap_date:
        sql += "AND sg.gap_date = :gap_date "
        params["gap_date"] = gap_date

    sql += "ORDER BY sg.gap_date, sg.shift_start"

    result = await db.execute(text(sql), params)
    rows = [dict(r) for r in result.mappings().fetchall()]

    items = [
        {
            "gap_id": str(row["id"]),
            "store_id": str(row["store_id"]),
            "gap_date": row["gap_date"].isoformat() if hasattr(row["gap_date"], "isoformat") else str(row["gap_date"]),
            "shift_start": str(row["shift_start"]),
            "shift_end": str(row["shift_end"]),
            "role": row["role"],
            "status": row["status"],
            "reason": row.get("reason"),
            "claimed_by": str(row["claimed_by"]) if row.get("claimed_by") else None,
            "claimed_by_name": row.get("claimed_by_name"),
            "filled_by": str(row["filled_by"]) if row.get("filled_by") else None,
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]

    log.info("gaps_listed", store_id=store_id, count=len(items), tenant_id=tenant_id)
    return _ok({"items": items, "total": len(items)})


@router.post("/gaps")
async def api_create_gap(
    req: CreateGapReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/gaps - 创建缺口（手动标记）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            "INSERT INTO shift_gaps "
            "(tenant_id, store_id, gap_date, shift_start, shift_end, role, reason, status) "
            "VALUES (:tid::uuid, :store_id::uuid, :gap_date, :start::time, :end::time, "
            ":role, :reason, 'open') "
            "RETURNING id, created_at"
        ),
        {
            "tid": tenant_id, "store_id": req.store_id,
            "gap_date": req.gap_date, "start": req.shift_start, "end": req.shift_end,
            "role": req.role, "reason": req.reason,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="创建缺口失败")

    row_data = dict(row)

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SHIFT_GAP_OPENED,
        tenant_id=UUID(tenant_id),
        stream_id=str(row_data["id"]),
        payload={
            "store_id": req.store_id, "gap_date": req.gap_date.isoformat(),
            "role": req.role, "shift_start": req.shift_start, "shift_end": req.shift_end,
        },
        store_id=UUID(req.store_id),
        source_service="tx-org",
    ))

    log.info("gap_created", gap_id=str(row_data["id"]), store_id=req.store_id, tenant_id=tenant_id)
    return _ok({
        "gap_id": str(row_data["id"]),
        "store_id": req.store_id,
        "gap_date": req.gap_date.isoformat(),
        "shift_start": req.shift_start,
        "shift_end": req.shift_end,
        "role": req.role,
        "status": "open",
        "created_at": str(row_data["created_at"]),
    })


@router.post("/gaps/{gap_id}/claim")
async def api_claim_gap(
    gap_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/gaps/{gap_id}/claim - 员工认领缺口"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 从 request.state 获取当前员工ID（由auth中间件设置）
    employee_id = getattr(request.state, "employee_id", None) or request.headers.get("X-Employee-ID")
    if not employee_id:
        raise HTTPException(status_code=400, detail="X-Employee-ID header required")

    result = await db.execute(
        text(
            "UPDATE shift_gaps "
            "SET status = 'claimed', claimed_by = :eid::uuid, updated_at = NOW() "
            "WHERE id = :gid::uuid AND tenant_id = :tid::uuid "
            "AND status = 'open' AND is_deleted = FALSE "
            "RETURNING id, store_id, gap_date, shift_start::text, shift_end::text, role"
        ),
        {"gid": gap_id, "tid": tenant_id, "eid": employee_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="缺口不存在或已被认领")

    row_data = dict(row)

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SHIFT_GAP_CLAIMED,
        tenant_id=UUID(tenant_id),
        stream_id=gap_id,
        payload={"gap_id": gap_id, "claimed_by": employee_id},
        store_id=UUID(str(row_data["store_id"])),
        source_service="tx-org",
    ))

    log.info("gap_claimed", gap_id=gap_id, employee_id=employee_id, tenant_id=tenant_id)
    return _ok({
        "gap_id": gap_id,
        "status": "claimed",
        "claimed_by": employee_id,
        "gap_date": row_data["gap_date"].isoformat() if hasattr(row_data["gap_date"], "isoformat") else str(row_data["gap_date"]),
        "role": row_data["role"],
    })


@router.post("/gaps/{gap_id}/fill")
async def api_fill_gap(
    gap_id: str,
    req: FillGapReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/gaps/{gap_id}/fill - 店长指派填补"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 获取缺口信息
    gap_result = await db.execute(
        text(
            "SELECT id, store_id, gap_date, shift_start::text, shift_end::text, role "
            "FROM shift_gaps "
            "WHERE id = :gid::uuid AND tenant_id = :tid::uuid "
            "AND status IN ('open', 'claimed') AND is_deleted = FALSE"
        ),
        {"gid": gap_id, "tid": tenant_id},
    )
    gap_row = gap_result.mappings().first()
    if gap_row is None:
        raise HTTPException(status_code=404, detail="缺口不存在或已填补")

    gap_data = dict(gap_row)

    # 为指派员工创建排班
    schedule_result = await db.execute(
        text(
            "INSERT INTO unified_schedules "
            "(tenant_id, store_id, employee_id, schedule_date, shift_start, shift_end, "
            "role, status, notes) "
            "VALUES (:tid::uuid, :store_id::uuid, :eid::uuid, :d, :start::time, :end::time, "
            ":role, 'scheduled', '缺口填补') "
            "RETURNING id"
        ),
        {
            "tid": tenant_id, "store_id": str(gap_data["store_id"]),
            "eid": req.employee_id, "d": gap_data["gap_date"],
            "start": str(gap_data["shift_start"]), "end": str(gap_data["shift_end"]),
            "role": gap_data["role"],
        },
    )
    new_schedule = schedule_result.mappings().first()

    # 更新缺口状态
    await db.execute(
        text(
            "UPDATE shift_gaps "
            "SET status = 'filled', filled_by = :eid::uuid, updated_at = NOW() "
            "WHERE id = :gid::uuid"
        ),
        {"gid": gap_id, "eid": req.employee_id},
    )

    asyncio.create_task(emit_event(
        event_type=OrgEventType.SHIFT_GAP_FILLED,
        tenant_id=UUID(tenant_id),
        stream_id=gap_id,
        payload={"gap_id": gap_id, "filled_by": req.employee_id},
        store_id=UUID(str(gap_data["store_id"])),
        source_service="tx-org",
    ))

    log.info("gap_filled", gap_id=gap_id, employee_id=req.employee_id, tenant_id=tenant_id)
    return _ok({
        "gap_id": gap_id,
        "status": "filled",
        "filled_by": req.employee_id,
        "new_schedule_id": str(new_schedule["id"]) if new_schedule else None,
    })


@router.post("/gaps/auto-detect")
async def api_auto_detect_gaps(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    gap_date: date = Query(..., alias="date", description="检测日期"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/gaps/auto-detect - 自动检测缺口（对比编制要求与排班）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    gaps = await auto_detect_gaps(db, tenant_id, store_id, gap_date)

    log.info("gaps_auto_detected", store_id=store_id, date=str(gap_date), gap_count=len(gaps), tenant_id=tenant_id)
    return _ok({
        "store_id": store_id,
        "date": gap_date.isoformat(),
        "detected_gaps": gaps,
        "gap_count": len(gaps),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  班次模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/templates")
async def api_get_templates(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店 ID（不传则返回全品牌模板）"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/templates - 班次模板列表"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = (
        "SELECT id, store_id, name, shift_start::text, shift_end::text, "
        "break_minutes, color, description, created_at "
        "FROM shift_templates "
        "WHERE tenant_id = :tid::uuid AND is_deleted = FALSE "
    )
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        sql += "AND store_id = :store_id::uuid "
        params["store_id"] = store_id

    sql += "ORDER BY shift_start"

    result = await db.execute(text(sql), params)
    rows = [dict(r) for r in result.mappings().fetchall()]

    items = [
        {
            "template_id": str(row["id"]),
            "store_id": str(row["store_id"]),
            "name": row["name"],
            "shift_start": str(row["shift_start"]),
            "shift_end": str(row["shift_end"]),
            "break_minutes": row.get("break_minutes", 0),
            "color": row.get("color"),
            "description": row.get("description"),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]

    log.info("templates_listed", store_id=store_id, count=len(items), tenant_id=tenant_id)
    return _ok({"items": items, "total": len(items)})


@router.post("/templates")
async def api_create_template(
    req: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/templates - 创建模板"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            "INSERT INTO shift_templates "
            "(tenant_id, store_id, name, shift_start, shift_end, break_minutes, color, description) "
            "VALUES (:tid::uuid, :store_id::uuid, :name, :start::time, :end::time, "
            ":break_min, :color, :desc) "
            "RETURNING id, created_at"
        ),
        {
            "tid": tenant_id, "store_id": req.store_id,
            "name": req.name, "start": req.shift_start, "end": req.shift_end,
            "break_min": req.break_minutes, "color": req.color, "desc": req.description,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="创建模板失败")

    row_data = dict(row)

    log.info("template_created", template_id=str(row_data["id"]), name=req.name, tenant_id=tenant_id)
    return _ok({
        "template_id": str(row_data["id"]),
        "store_id": req.store_id,
        "name": req.name,
        "shift_start": req.shift_start,
        "shift_end": req.shift_end,
        "break_minutes": req.break_minutes,
        "color": req.color,
        "description": req.description,
        "created_at": str(row_data["created_at"]),
    })


@router.put("/templates/{template_id}")
async def api_update_template(
    template_id: str,
    req: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PUT /api/v1/schedules/templates/{template_id} - 更新模板"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    changes = {k: v for k, v in req.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(status_code=400, detail="未提供任何需要更新的字段")

    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"tid": tenant_id, "tmpl_id": template_id}

    field_map = {
        "name": "name = :name",
        "shift_start": "shift_start = :shift_start::time",
        "shift_end": "shift_end = :shift_end::time",
        "break_minutes": "break_minutes = :break_minutes",
        "color": "color = :color",
        "description": "description = :description",
    }
    for field_name, sql_expr in field_map.items():
        val = getattr(req, field_name, None)
        if val is not None:
            set_parts.append(sql_expr)
            params[field_name] = val

    set_clause = ", ".join(set_parts)

    result = await db.execute(
        text(
            f"UPDATE shift_templates SET {set_clause} "
            "WHERE id = :tmpl_id::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE "
            "RETURNING id, store_id, name, shift_start::text, shift_end::text, "
            "break_minutes, color, description"
        ),
        params,
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")

    row_data = dict(row)

    log.info("template_updated", template_id=template_id, changes=changes, tenant_id=tenant_id)
    return _ok({
        "template_id": str(row_data["id"]),
        "store_id": str(row_data["store_id"]),
        "name": row_data["name"],
        "shift_start": str(row_data["shift_start"]),
        "shift_end": str(row_data["shift_end"]),
        "break_minutes": row_data.get("break_minutes", 0),
        "color": row_data.get("color"),
        "description": row_data.get("description"),
    })


@router.delete("/templates/{template_id}")
async def api_delete_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """DELETE /api/v1/schedules/templates/{template_id} - 删除模板"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            "UPDATE shift_templates SET is_deleted = TRUE, updated_at = NOW() "
            "WHERE id = :tmpl_id::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE "
            "RETURNING id, name"
        ),
        {"tmpl_id": template_id, "tid": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在或已删除")

    log.info("template_deleted", template_id=template_id, tenant_id=tenant_id)
    return _ok({"template_id": template_id, "deleted": True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/statistics")
async def api_get_statistics(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/statistics - 排班统计（总工时/人均工时/缺口率/调班率）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 解析月份为日期范围
    year, mon = month.split("-")
    month_start = date(int(year), int(mon), 1)
    if int(mon) == 12:
        month_end = date(int(year) + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(int(year), int(mon) + 1, 1) - timedelta(days=1)

    # 排班统计
    schedule_stats = await db.execute(
        text(
            "SELECT "
            "COUNT(*) AS total_shifts, "
            "COUNT(DISTINCT employee_id) AS employee_count, "
            "SUM(EXTRACT(EPOCH FROM (shift_end - shift_start)) / 3600) AS total_hours, "
            "COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count "
            "FROM unified_schedules "
            "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
            "AND schedule_date BETWEEN :start AND :end "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "store_id": store_id, "start": month_start, "end": month_end},
    )
    s_row = dict(schedule_stats.mappings().first())

    total_shifts = s_row.get("total_shifts", 0) or 0
    employee_count = s_row.get("employee_count", 0) or 0
    total_hours = float(s_row.get("total_hours", 0) or 0)
    cancelled_count = s_row.get("cancelled_count", 0) or 0

    # 缺口统计
    gap_stats = await db.execute(
        text(
            "SELECT "
            "COUNT(*) AS total_gaps, "
            "COUNT(*) FILTER (WHERE status = 'filled') AS filled_gaps, "
            "COUNT(*) FILTER (WHERE status = 'open') AS open_gaps "
            "FROM shift_gaps "
            "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
            "AND gap_date BETWEEN :start AND :end "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "store_id": store_id, "start": month_start, "end": month_end},
    )
    g_row = dict(gap_stats.mappings().first())

    total_gaps = g_row.get("total_gaps", 0) or 0
    filled_gaps = g_row.get("filled_gaps", 0) or 0
    open_gaps = g_row.get("open_gaps", 0) or 0

    # 调班统计
    swap_stats = await db.execute(
        text(
            "SELECT "
            "COUNT(*) AS total_swaps, "
            "COUNT(*) FILTER (WHERE status = 'approved') AS approved_swaps "
            "FROM schedule_swap_requests "
            "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
            "AND created_at >= :start::date AND created_at < (:end::date + interval '1 day')"
        ),
        {"tid": tenant_id, "store_id": store_id, "start": month_start, "end": month_end},
    )
    sw_row = dict(swap_stats.mappings().first())

    total_swaps = sw_row.get("total_swaps", 0) or 0
    approved_swaps = sw_row.get("approved_swaps", 0) or 0

    avg_hours = round(total_hours / employee_count, 1) if employee_count > 0 else 0
    gap_rate = round(total_gaps / total_shifts * 100, 1) if total_shifts > 0 else 0
    swap_rate = round(total_swaps / total_shifts * 100, 1) if total_shifts > 0 else 0

    log.info("statistics_queried", store_id=store_id, month=month, tenant_id=tenant_id)
    return _ok({
        "store_id": store_id,
        "month": month,
        "schedule": {
            "total_shifts": total_shifts,
            "employee_count": employee_count,
            "total_hours": round(total_hours, 1),
            "avg_hours_per_employee": avg_hours,
            "cancelled_count": cancelled_count,
        },
        "gaps": {
            "total_gaps": total_gaps,
            "filled_gaps": filled_gaps,
            "open_gaps": open_gaps,
            "gap_rate_pct": gap_rate,
        },
        "swaps": {
            "total_swaps": total_swaps,
            "approved_swaps": approved_swaps,
            "swap_rate_pct": swap_rate,
        },
    })
