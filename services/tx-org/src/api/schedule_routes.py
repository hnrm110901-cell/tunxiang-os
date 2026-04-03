"""排班管理 API 路由（新版，基于 work_schedules 表）

端点列表（prefix=/api/v1/schedules）：
  GET  /api/v1/schedules/week                     获取周排班（7天×全员）
  POST /api/v1/schedules                           创建单条排班
  POST /api/v1/schedules/batch                     批量创建排班（一键排班）
  PUT  /api/v1/schedules/{schedule_id}             修改排班（调班/取消/换人）
  DELETE /api/v1/schedules/{schedule_id}           取消排班
  GET  /api/v1/schedules/conflicts                 检测排班冲突

待迁移数据表（API层面约定，尚未建表，表不存在时返回 TABLE_NOT_READY）：
  work_schedules:
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
    tenant_id     UUID NOT NULL
    store_id      TEXT NOT NULL
    employee_id   TEXT NOT NULL
    schedule_date DATE NOT NULL
    shift_start   TIME NOT NULL
    shift_end     TIME NOT NULL
    role          TEXT
    status        TEXT DEFAULT 'planned'   -- planned/confirmed/cancelled
    notes         TEXT
    created_at    TIMESTAMPTZ DEFAULT NOW()
    updated_at    TIMESTAMPTZ DEFAULT NOW()
    is_deleted    BOOLEAN DEFAULT FALSE
    CONSTRAINT work_schedules_no_overlap UNIQUE (tenant_id, employee_id, schedule_date, shift_start)

  RLS: CREATE POLICY tenant_isolation ON work_schedules
       USING (tenant_id = current_setting('app.tenant_id')::uuid);

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])


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


def _table_not_ready() -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": "TABLE_NOT_READY",
            "message": "排班模块待数据库迁移，敬请期待",
        },
    }


def _is_table_missing(exc: Exception) -> bool:
    return "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc)


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
    role: Optional[str] = Field(None, description="排班岗位（如收银/服务员/厨师）")
    notes: Optional[str] = Field(None, description="备注")


class BatchShiftItem(BaseModel):
    day: int = Field(..., ge=0, le=6, description="星期偏移量 0=周一 ... 6=周日")
    start: str = Field(..., description="班次开始 HH:MM")
    end: str = Field(..., description="班次结束 HH:MM")


class BatchEmployeeTemplate(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    shifts: list[BatchShiftItem] = Field(..., description="该员工的排班模板")


class BatchCreateScheduleReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    week_start: date = Field(..., description="周起始日 YYYY-MM-DD（通常为周一）")
    template: list[BatchEmployeeTemplate] = Field(..., description="排班模板列表")


class UpdateScheduleReq(BaseModel):
    shift_start: Optional[str] = Field(None, description="新的班次开始时间 HH:MM")
    shift_end: Optional[str] = Field(None, description="新的班次结束时间 HH:MM")
    employee_id: Optional[str] = Field(None, description="换人：新员工 ID")
    status: Optional[str] = Field(None, description="状态：planned/confirmed/cancelled")
    role: Optional[str] = Field(None, description="岗位")
    notes: Optional[str] = Field(None, description="备注")


# ── GET /week ─────────────────────────────────────────────────────────────────


@router.get("/week")
async def get_week_schedule(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    week_start: date = Query(..., description="周起始日 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/week — 获取周排班（7天 × 全员）

    返回格式：
    {
      "dates": ["2026-04-07", ...],
      "employees": [
        {
          "employee_id": "...",
          "name": "...",
          "role": "...",
          "shifts": [{"date": "...", "start": "...", "end": "...", "status": "..."}]
        }
      ]
    }

    依赖数据表：work_schedules（待迁移），employees（已存在）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    week_end = week_start + timedelta(days=6)
    dates = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]

    try:
        result = await db.execute(
            text(
                "SELECT ws.id, ws.employee_id, ws.schedule_date, "
                "ws.shift_start::text AS shift_start, ws.shift_end::text AS shift_end, "
                "ws.role, ws.status, ws.notes, "
                "e.name AS employee_name "
                "FROM work_schedules ws "
                "LEFT JOIN employees e ON e.id = ws.employee_id::uuid "
                "   AND e.tenant_id = ws.tenant_id AND e.is_deleted = FALSE "
                "WHERE ws.tenant_id = :tid "
                "AND ws.store_id = :store_id "
                "AND ws.schedule_date BETWEEN :week_start AND :week_end "
                "AND COALESCE(ws.is_deleted, FALSE) = FALSE "
                "ORDER BY ws.employee_id, ws.schedule_date, ws.shift_start"
            ),
            {"tid": tenant_id, "store_id": store_id, "week_start": week_start, "week_end": week_end},
        )
        rows = [dict(r) for r in result.mappings().fetchall()]
    except Exception as exc:
        if _is_table_missing(exc):
            return _table_not_ready()
        raise

    # 按员工聚合
    emp_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = str(row["employee_id"])
        if eid not in emp_map:
            emp_map[eid] = {
                "employee_id": eid,
                "name": row.get("employee_name"),
                "role": row.get("role"),
                "shifts": [],
            }
        emp_map[eid]["shifts"].append({
            "schedule_id": str(row["id"]),
            "date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
            "start": str(row["shift_start"]),
            "end": str(row["shift_end"]),
            "status": row.get("status", "planned"),
            "notes": row.get("notes"),
        })

    log.info(
        "week_schedule_queried",
        extra={"store_id": store_id, "week_start": str(week_start), "tenant_id": tenant_id},
    )

    return _ok({
        "store_id": store_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "dates": dates,
        "employees": list(emp_map.values()),
        "total_shifts": len(rows),
    })


# ── POST / ────────────────────────────────────────────────────────────────────


@router.post("")
async def create_schedule(
    req: CreateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules — 创建单条排班

    依赖数据表：work_schedules（待迁移）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    try:
        result = await db.execute(
            text(
                "INSERT INTO work_schedules "
                "(tenant_id, store_id, employee_id, schedule_date, shift_start, shift_end, "
                "role, status, notes) "
                "VALUES (:tid, :store_id, :employee_id, :schedule_date, "
                ":shift_start::time, :shift_end::time, :role, 'planned', :notes) "
                "RETURNING id, schedule_date, shift_start::text, shift_end::text, status"
            ),
            {
                "tid": tenant_id,
                "store_id": req.store_id,
                "employee_id": req.employee_id,
                "schedule_date": req.schedule_date,
                "shift_start": req.shift_start,
                "shift_end": req.shift_end,
                "role": req.role,
                "notes": req.notes,
            },
        )
        row = result.mappings().first()
    except Exception as exc:
        if _is_table_missing(exc):
            return _table_not_ready()
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="创建排班失败")

    log.info(
        "schedule_created",
        extra={
            "employee_id": req.employee_id,
            "store_id": req.store_id,
            "schedule_date": str(req.schedule_date),
            "tenant_id": tenant_id,
        },
    )

    return _ok({
        "schedule_id": str(row["id"]),
        "employee_id": req.employee_id,
        "store_id": req.store_id,
        "schedule_date": req.schedule_date.isoformat(),
        "shift_start": str(row["shift_start"]),
        "shift_end": str(row["shift_end"]),
        "status": row["status"],
    })


# ── POST /batch ───────────────────────────────────────────────────────────────


@router.post("/batch")
async def batch_create_schedules(
    req: BatchCreateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/schedules/batch — 批量创建排班（一键排班）

    按模板为多名员工生成一周排班，忽略冲突（ON CONFLICT DO NOTHING）。

    依赖数据表：work_schedules（待迁移）
    表需要唯一约束：UNIQUE (tenant_id, employee_id, schedule_date, shift_start)
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    inserted = 0
    skipped = 0

    for emp_tpl in req.template:
        for shift in emp_tpl.shifts:
            if shift.day < 0 or shift.day > 6:
                raise HTTPException(
                    status_code=400,
                    detail=f"员工 {emp_tpl.employee_id} 的 day 值 {shift.day} 无效，须为 0-6",
                )
            target_date = req.week_start + timedelta(days=shift.day)
            try:
                result = await db.execute(
                    text(
                        "INSERT INTO work_schedules "
                        "(tenant_id, store_id, employee_id, schedule_date, shift_start, shift_end, "
                        "status) "
                        "VALUES (:tid, :store_id, :employee_id, :schedule_date, "
                        ":shift_start::time, :shift_end::time, 'planned') "
                        "ON CONFLICT (tenant_id, employee_id, schedule_date, shift_start) DO NOTHING "
                        "RETURNING id"
                    ),
                    {
                        "tid": tenant_id,
                        "store_id": req.store_id,
                        "employee_id": emp_tpl.employee_id,
                        "schedule_date": target_date,
                        "shift_start": shift.start,
                        "shift_end": shift.end,
                    },
                )
                row = result.mappings().first()
                if row is not None:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:
                if _is_table_missing(exc):
                    return _table_not_ready()
                raise

    log.info(
        "schedules_batch_created",
        extra={
            "store_id": req.store_id,
            "week_start": str(req.week_start),
            "tenant_id": tenant_id,
            "inserted": inserted,
            "skipped": skipped,
        },
    )

    return _ok({
        "store_id": req.store_id,
        "week_start": req.week_start.isoformat(),
        "inserted": inserted,
        "skipped_conflicts": skipped,
        "total_attempted": inserted + skipped,
    })


# ── PUT /{schedule_id} ────────────────────────────────────────────────────────


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    req: UpdateScheduleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PUT /api/v1/schedules/{schedule_id} — 修改排班（调班/取消/换人）

    支持：
    - 修改时间（shift_start / shift_end）
    - 取消排班（status=cancelled）
    - 换人（替换 employee_id）

    依赖数据表：work_schedules（待迁移）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.status and req.status not in ("planned", "confirmed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail="status 须为 planned / confirmed / cancelled",
        )

    # 构造动态 SET 子句
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"schedule_id": schedule_id, "tid": tenant_id}

    if req.shift_start is not None:
        set_parts.append("shift_start = :shift_start::time")
        params["shift_start"] = req.shift_start
    if req.shift_end is not None:
        set_parts.append("shift_end = :shift_end::time")
        params["shift_end"] = req.shift_end
    if req.employee_id is not None:
        set_parts.append("employee_id = :new_employee_id")
        params["new_employee_id"] = req.employee_id
    if req.status is not None:
        set_parts.append("status = :status")
        params["status"] = req.status
    if req.role is not None:
        set_parts.append("role = :role")
        params["role"] = req.role
    if req.notes is not None:
        set_parts.append("notes = :notes")
        params["notes"] = req.notes

    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="未提供任何需要更新的字段")

    set_clause = ", ".join(set_parts)

    try:
        result = await db.execute(
            text(
                f"UPDATE work_schedules SET {set_clause} "
                "WHERE id = :schedule_id AND tenant_id = :tid "
                "AND COALESCE(is_deleted, FALSE) = FALSE "
                "RETURNING id, employee_id, schedule_date, "
                "shift_start::text, shift_end::text, status, role, notes"
            ),
            params,
        )
        row = result.mappings().first()
    except Exception as exc:
        if _is_table_missing(exc):
            return _table_not_ready()
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="排班记录不存在")

    log.info(
        "schedule_updated",
        extra={
            "schedule_id": schedule_id,
            "tenant_id": tenant_id,
            "changes": {k: v for k, v in req.model_dump().items() if v is not None},
        },
    )

    return _ok({
        "schedule_id": str(row["id"]),
        "employee_id": str(row["employee_id"]),
        "schedule_date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
        "shift_start": str(row["shift_start"]),
        "shift_end": str(row["shift_end"]),
        "status": row["status"],
        "role": row.get("role"),
        "notes": row.get("notes"),
    })


# ── DELETE /{schedule_id} ─────────────────────────────────────────────────────


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """DELETE /api/v1/schedules/{schedule_id} — 取消排班（软删除）

    依赖数据表：work_schedules（待迁移）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    try:
        result = await db.execute(
            text(
                "UPDATE work_schedules SET status = 'cancelled', is_deleted = TRUE, "
                "updated_at = NOW() "
                "WHERE id = :schedule_id AND tenant_id = :tid "
                "AND COALESCE(is_deleted, FALSE) = FALSE "
                "RETURNING id, employee_id, schedule_date"
            ),
            {"schedule_id": schedule_id, "tid": tenant_id},
        )
        row = result.mappings().first()
    except Exception as exc:
        if _is_table_missing(exc):
            return _table_not_ready()
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="排班记录不存在或已取消")

    log.info(
        "schedule_cancelled",
        extra={
            "schedule_id": schedule_id,
            "employee_id": str(row["employee_id"]),
            "tenant_id": tenant_id,
        },
    )

    return _ok({
        "schedule_id": str(row["id"]),
        "employee_id": str(row["employee_id"]),
        "schedule_date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
        "status": "cancelled",
    })


# ── GET /conflicts ────────────────────────────────────────────────────────────


@router.get("/conflicts")
async def get_schedule_conflicts(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    week_start: date = Query(..., description="周起始日 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedules/conflicts — 检测同员工同日班次时间重叠冲突

    检测逻辑：同一租户、同一员工、同一日期，存在两条或以上的排班记录，
    且班次时间段存在重叠（shift_start < other.shift_end AND shift_end > other.shift_start）。

    依赖数据表：work_schedules（待迁移）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    week_end = week_start + timedelta(days=6)

    try:
        result = await db.execute(
            text(
                "SELECT a.id AS schedule_id_a, b.id AS schedule_id_b, "
                "a.employee_id, a.schedule_date, "
                "a.shift_start::text AS start_a, a.shift_end::text AS end_a, "
                "b.shift_start::text AS start_b, b.shift_end::text AS end_b "
                "FROM work_schedules a "
                "JOIN work_schedules b "
                "  ON a.tenant_id = b.tenant_id "
                "  AND a.employee_id = b.employee_id "
                "  AND a.schedule_date = b.schedule_date "
                "  AND a.id < b.id "
                "  AND a.shift_start < b.shift_end "
                "  AND a.shift_end > b.shift_start "
                "WHERE a.tenant_id = :tid "
                "AND a.store_id = :store_id "
                "AND a.schedule_date BETWEEN :week_start AND :week_end "
                "AND COALESCE(a.is_deleted, FALSE) = FALSE "
                "AND COALESCE(b.is_deleted, FALSE) = FALSE "
                "AND a.status != 'cancelled' "
                "AND b.status != 'cancelled' "
                "ORDER BY a.schedule_date, a.employee_id"
            ),
            {"tid": tenant_id, "store_id": store_id, "week_start": week_start, "week_end": week_end},
        )
        rows = [dict(r) for r in result.mappings().fetchall()]
    except Exception as exc:
        if _is_table_missing(exc):
            return _table_not_ready()
        raise

    conflicts = [
        {
            "employee_id": str(row["employee_id"]),
            "date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
            "conflict_a": {
                "schedule_id": str(row["schedule_id_a"]),
                "shift_start": str(row["start_a"]),
                "shift_end": str(row["end_a"]),
            },
            "conflict_b": {
                "schedule_id": str(row["schedule_id_b"]),
                "shift_start": str(row["start_b"]),
                "shift_end": str(row["end_b"]),
            },
        }
        for row in rows
    ]

    log.info(
        "schedule_conflicts_checked",
        extra={
            "store_id": store_id,
            "week_start": str(week_start),
            "conflicts_found": len(conflicts),
            "tenant_id": tenant_id,
        },
    )

    return _ok({
        "store_id": store_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "has_conflicts": len(conflicts) > 0,
    })
