"""考勤打卡 API 路由

端点列表：
  POST /api/v1/attendance/clock-in          打卡上班
  POST /api/v1/attendance/clock-out         打卡下班
  GET  /api/v1/attendance/daily             指定日期门店打卡状态
  GET  /api/v1/attendance/summary           月度考勤汇总
  GET  /api/v1/attendance/monthly-summary   月度考勤月报（与 summary 同源）
  GET  /api/v1/attendance/anomalies         考勤异常列表
  GET  /api/v1/attendance/payroll-data      薪资引擎数据接口
  POST /api/v1/attendance/mark-absent       手动触发缺勤标记（运维/定时任务）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.attendance_engine import CLOCK_METHODS
from ..services.attendance_repository import (
    create_clock_record,
    get_attendance_anomalies,
    get_attendance_rule,
    get_daily_attendance_for_store,
    get_employee_schedule,
    get_open_clock_in,
    get_payroll_attendance_data,
    mark_absent_employees,
    update_clock_out_pair,
    upsert_daily_attendance,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["attendance"])

# 迟到等级阈值（分钟）
_LATE_MINOR_THRESHOLD = 5
_LATE_MAJOR_THRESHOLD = 30
# 早退宽限（分钟）
_EARLY_LEAVE_GRACE = 5
# 加班最低认定（分钟）
_OVERTIME_MIN = 30


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class ClockInReq(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    store_id: str = Field(..., description="门店 ID")
    location_lat: Optional[float] = Field(None, description="打卡纬度")
    location_lng: Optional[float] = Field(None, description="打卡经度")
    device_id: Optional[str] = Field(None, description="设备 ID")
    method: str = Field(default="device", description="打卡方式: device/face/app/manual")
    clock_time: Optional[datetime] = Field(None, description="打卡时间（留空=服务器当前时间）")


class ClockOutReq(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    store_id: str = Field(..., description="门店 ID")
    method: str = Field(default="device", description="打卡方式: device/face/app/manual")
    clock_time: Optional[datetime] = Field(None, description="打卡时间（留空=服务器当前时间）")


class MarkAbsentReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    work_date: date = Field(..., description="目标日期")


# ── 打卡核心逻辑 ──────────────────────────────────────────────────────────────


def _build_location_str(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    return None


def _calculate_clock_in_status(
    clock_time: datetime,
    shift_start: Optional[Any],
    grace_minutes: int,
) -> tuple[str, int]:
    """计算打卡上班状态和与排班时间的差值（分钟）

    Returns:
        (status, diff_minutes) — diff_minutes > 0 表示迟到
    """
    if shift_start is None:
        return "unscheduled", 0

    # shift_start 可能是 time 对象或 datetime
    if hasattr(shift_start, "hour"):
        from datetime import time as t_type
        if isinstance(shift_start, t_type):
            scheduled_dt = datetime.combine(clock_time.date(), shift_start)
            if clock_time.tzinfo:
                scheduled_dt = scheduled_dt.replace(tzinfo=clock_time.tzinfo)
        else:
            scheduled_dt = shift_start
    else:
        scheduled_dt = shift_start

    diff = int((clock_time - scheduled_dt).total_seconds() / 60)

    if diff > _LATE_MAJOR_THRESHOLD or diff > grace_minutes:
        status = "late"
    elif diff < -60:
        status = "early"  # 提前超过1小时，需确认
    else:
        status = "on_time"

    return status, diff


def _calculate_clock_out_status(
    clock_time: datetime,
    shift_end: Optional[Any],
    grace_minutes: int,
    overtime_min: int,
) -> tuple[str, int, float]:
    """计算打卡下班状态、差值（分钟）和加班小时数

    Returns:
        (status, diff_minutes, overtime_hours)
    """
    if shift_end is None:
        return "unscheduled", 0, 0.0

    if hasattr(shift_end, "hour"):
        from datetime import time as t_type
        if isinstance(shift_end, t_type):
            scheduled_dt = datetime.combine(clock_time.date(), shift_end)
            if clock_time.tzinfo:
                scheduled_dt = scheduled_dt.replace(tzinfo=clock_time.tzinfo)
        else:
            scheduled_dt = shift_end
    else:
        scheduled_dt = shift_end

    diff = int((clock_time - scheduled_dt).total_seconds() / 60)

    if diff < -grace_minutes:
        status = "early_leave"
        overtime_hours = 0.0
    elif diff >= overtime_min:
        status = "overtime"
        overtime_hours = round(diff / 60, 2)
    else:
        status = "on_time"
        overtime_hours = 0.0

    return status, diff, overtime_hours


# ── 端点 ──────────────────────────────────────────────────────────────────────


async def _monthly_summary_payload(
    store_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    rows = await db.execute(
        text(
            "SELECT employee_id, "
            "COUNT(*) FILTER (WHERE status IN ('normal','late','early_leave','overtime')) AS work_days, "
            "COUNT(*) FILTER (WHERE status = 'absent') AS absent_days, "
            "COUNT(*) FILTER (WHERE status = 'late') AS late_times, "
            "COUNT(*) FILTER (WHERE status = 'early_leave') AS early_leave_times, "
            "COALESCE(SUM(work_hours), 0) AS total_work_hours, "
            "COALESCE(SUM(overtime_hours), 0) AS overtime_hours, "
            "COUNT(*) FILTER (WHERE status = 'on_leave') AS on_leave_days "
            "FROM daily_attendance "
            "WHERE tenant_id = :tid AND store_id = :sid "
            "AND TO_CHAR(date, 'YYYY-MM') = :month "
            "AND is_deleted = FALSE "
            "GROUP BY employee_id ORDER BY employee_id"
        ),
        {"tid": tenant_id, "sid": store_id, "month": month},
    )
    items = [dict(r) for r in rows.mappings().fetchall()]
    return {
        "store_id": store_id,
        "month": month,
        "items": items,
        "total": len(items),
    }


@router.post("/api/v1/attendance/clock-in")
async def clock_in(
    req: ClockInReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/attendance/clock-in — 员工打卡上班

    - 验证打卡方式
    - 检查是否在排班时间内
    - 标记迟到状态
    - 写入 clock_records + upsert daily_attendance
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.method not in CLOCK_METHODS:
        raise HTTPException(status_code=400, detail=f"不支持的打卡方式: {req.method}")

    clock_time = req.clock_time or datetime.now(tz=timezone.utc)
    work_date = clock_time.date()

    # 检查是否已有今日打卡记录
    existing = await get_open_clock_in(req.employee_id, work_date, tenant_id, db)
    if existing:
        raise HTTPException(status_code=409, detail="今日已有未闭合的打卡记录，请先打卡下班")

    # 查询排班
    schedule = await get_employee_schedule(req.employee_id, work_date, tenant_id, db)

    # 查询考勤规则
    rule = await get_attendance_rule(req.store_id, tenant_id, db)
    grace_minutes = rule["grace_period_minutes"] if rule else 5

    shift_name: Optional[str] = None
    shift_start_time = None

    if schedule and not schedule.get("is_day_off"):
        shift_name = schedule.get("shift_name")
        shift_start_time = schedule.get("shift_start_time")

    status, diff_minutes = _calculate_clock_in_status(clock_time, shift_start_time, grace_minutes)

    # 构造 scheduled_time
    scheduled_time: Optional[datetime] = None
    if shift_start_time is not None:
        from datetime import time as t_type
        if isinstance(shift_start_time, t_type):
            scheduled_time = datetime.combine(work_date, shift_start_time)

    location = _build_location_str(req.location_lat, req.location_lng)

    clock_record = await create_clock_record(
        tenant_id=tenant_id,
        store_id=req.store_id,
        employee_id=req.employee_id,
        clock_type="in",
        clock_time=clock_time,
        method=req.method,
        scheduled_shift=shift_name,
        scheduled_time=scheduled_time,
        status=status,
        diff_minutes=diff_minutes,
        device_info=req.device_id,
        location=location,
        db=db,
    )

    # 计算迟到分钟数
    late_minutes = max(0, diff_minutes) if status == "late" else 0

    # Upsert daily_attendance（打卡上班时先写入，下班后更新）
    await upsert_daily_attendance(
        tenant_id=tenant_id,
        store_id=req.store_id,
        employee_id=req.employee_id,
        work_date=work_date,
        clock_in_id=UUID(str(clock_record["id"])),
        clock_in_time=clock_time,
        status=status,
        late_minutes=late_minutes,
        scheduled_shift=shift_name,
        db=db,
    )

    log.info(
        "clock_in",
        extra={
            "employee_id": req.employee_id,
            "store_id": req.store_id,
            "status": status,
            "diff_minutes": diff_minutes,
            "tenant_id": tenant_id,
        },
    )

    return _ok({
        "clock_record_id": str(clock_record["id"]),
        "employee_id": req.employee_id,
        "clock_time": clock_time.isoformat(),
        "status": status,
        "diff_minutes": diff_minutes,
        "scheduled_shift": shift_name,
        "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
        "late_minutes": late_minutes,
    })


@router.post("/api/v1/attendance/clock-out")
async def clock_out(
    req: ClockOutReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/attendance/clock-out — 员工打卡下班

    - 找到今日未闭合的 clock_in 记录
    - 计算实际工作时长
    - 更新 clock_records（配对关联）
    - 触发 daily_attendance 聚合更新
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    clock_time = req.clock_time or datetime.now(tz=timezone.utc)
    work_date = clock_time.date()

    # 查找今日未闭合的 clock_in
    open_in = await get_open_clock_in(req.employee_id, work_date, tenant_id, db)
    if not open_in:
        raise HTTPException(status_code=404, detail="未找到今日打卡上班记录，请先打卡上班")

    # 查询排班（用于判断早退/加班）
    schedule = await get_employee_schedule(req.employee_id, work_date, tenant_id, db)
    rule = await get_attendance_rule(req.store_id, tenant_id, db)
    grace_minutes = rule["early_leave_grace_minutes"] if rule else 5
    overtime_min = rule["overtime_min_minutes"] if rule else 30

    shift_name: Optional[str] = open_in.get("scheduled_shift")
    shift_end_time = None
    if schedule and not schedule.get("is_day_off"):
        shift_end_time = schedule.get("shift_end_time")

    out_status, diff_minutes, overtime_hours = _calculate_clock_out_status(
        clock_time, shift_end_time, grace_minutes, overtime_min
    )

    # 计算工作时长
    clock_in_time: datetime = open_in["clock_time"]
    if clock_in_time.tzinfo is None and clock_time.tzinfo is not None:
        clock_in_time = clock_in_time.replace(tzinfo=timezone.utc)
    work_seconds = (clock_time - clock_in_time).total_seconds()
    work_hours = round(work_seconds / 3600, 2)

    location = _build_location_str(None, None)

    # 写入 clock_out 记录
    clock_out_record = await create_clock_record(
        tenant_id=tenant_id,
        store_id=req.store_id,
        employee_id=req.employee_id,
        clock_type="out",
        clock_time=clock_time,
        method=req.method,
        scheduled_shift=shift_name,
        scheduled_time=None,
        status=out_status,
        diff_minutes=diff_minutes,
        device_info=None,
        location=location,
        db=db,
    )

    # 关联 clock_in 与 clock_out
    await update_clock_out_pair(
        clock_in_id=UUID(str(open_in["id"])),
        clock_out_id=UUID(str(clock_out_record["id"])),
        work_hours=work_hours,
        tenant_id=tenant_id,
        db=db,
    )

    # 综合状态：优先展示迟到（已在 clock_in 记录），出勤状态取下班状态
    in_status = open_in.get("status", "on_time")
    if in_status == "late":
        final_status = "late"
    else:
        final_status = out_status if out_status != "unscheduled" else "normal"
    if in_status == "on_time" and out_status == "on_time":
        final_status = "normal"

    early_leave_minutes = abs(diff_minutes) if out_status == "early_leave" else 0

    # 获取 clock_in 的 late_minutes（从 daily_attendance 已有记录）
    # Upsert daily_attendance（更新完整记录）
    scheduled_time_out: Optional[datetime] = None
    if shift_end_time is not None:
        from datetime import time as t_type
        if isinstance(shift_end_time, t_type):
            scheduled_time_out = datetime.combine(work_date, shift_end_time)

    await upsert_daily_attendance(
        tenant_id=tenant_id,
        store_id=req.store_id,
        employee_id=req.employee_id,
        work_date=work_date,
        clock_in_id=UUID(str(open_in["id"])),
        clock_out_id=UUID(str(clock_out_record["id"])),
        clock_in_time=clock_in_time,
        clock_out_time=clock_time,
        status=final_status,
        work_hours=work_hours,
        overtime_hours=overtime_hours,
        early_leave_minutes=early_leave_minutes,
        scheduled_shift=shift_name,
        db=db,
    )

    log.info(
        "clock_out",
        extra={
            "employee_id": req.employee_id,
            "status": out_status,
            "work_hours": work_hours,
            "overtime_hours": overtime_hours,
        },
    )

    return _ok({
        "clock_record_id": str(clock_out_record["id"]),
        "clock_in_id": str(open_in["id"]),
        "employee_id": req.employee_id,
        "clock_time": clock_time.isoformat(),
        "status": out_status,
        "final_daily_status": final_status,
        "diff_minutes": diff_minutes,
        "work_hours": work_hours,
        "overtime_hours": overtime_hours,
        "early_leave_minutes": early_leave_minutes,
    })


@router.get("/api/v1/attendance/daily")
async def get_daily_attendance(
    store_id: str = Query(..., description="门店 ID"),
    target_date: date = Query(..., alias="date", description="目标日期 YYYY-MM-DD"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/daily — 指定日期所有员工的打卡状态"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    records = await get_daily_attendance_for_store(store_id, target_date, tenant_id, db)

    return _ok({
        "store_id": store_id,
        "date": target_date.isoformat(),
        "items": records,
        "total": len(records),
    })


@router.get("/api/v1/attendance/summary")
async def get_attendance_summary(
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/summary — 月度考勤汇总（按员工聚合）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)
    payload = await _monthly_summary_payload(store_id, month, tenant_id, db)
    return _ok(payload)


@router.get("/api/v1/attendance/monthly-summary")
async def get_monthly_attendance_summary(
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/monthly-summary — 获取某门店某月的考勤月报"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)
    payload = await _monthly_summary_payload(store_id, month, tenant_id, db)
    return _ok(payload)


@router.get("/api/v1/attendance/anomalies")
async def list_attendance_anomalies(
    store_id: str = Query(..., description="门店 ID"),
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/anomalies — 考勤异常列表（迟到/早退/旷工/缺卡）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date 不能早于 start_date")
    if (end_date - start_date).days > 93:  # ~3个月
        raise HTTPException(status_code=400, detail="日期范围不能超过 93 天")

    anomalies = await get_attendance_anomalies(store_id, start_date, end_date, tenant_id, db)

    return _ok({
        "store_id": store_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "items": anomalies,
        "total": len(anomalies),
    })


@router.get("/api/v1/attendance/payroll-data")
async def get_payroll_data(
    employee_id: str = Query(..., description="员工 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/payroll-data — 薪资引擎考勤数据接口

    薪资引擎调用此接口获取月度考勤数据用于计算扣款。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 查询门店的考勤规则（迟到扣款）
    # 因为 employee_id 可能跨门店，先查员工所在门店
    emp_row = await db.execute(
        text(
            "SELECT store_id FROM employees "
            "WHERE id = :eid AND tenant_id = :tid AND is_deleted = FALSE LIMIT 1"
        ),
        {"eid": employee_id, "tid": tenant_id},
    )
    emp = emp_row.mappings().first()
    store_id = emp["store_id"] if emp else None
    late_deduction_fen = 5000  # 默认
    if store_id:
        rule = await get_attendance_rule(store_id, tenant_id, db)
        if rule:
            late_deduction_fen = rule.get("late_deduction_fen", 5000)

    data = await get_payroll_attendance_data(
        employee_id=employee_id,
        month=month,
        tenant_id=tenant_id,
        db=db,
        late_deduction_fen=late_deduction_fen,
    )

    return _ok(data)


@router.post("/api/v1/attendance/mark-absent")
async def mark_absent(
    req: MarkAbsentReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/attendance/mark-absent — 触发缺勤自动标记

    由定时任务（每天结束后）或运维人员手动调用。
    检查有排班但无打卡且无请假的员工，标记为 absent。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    count = await mark_absent_employees(req.store_id, req.work_date, tenant_id, db)

    return _ok({
        "store_id": req.store_id,
        "work_date": req.work_date.isoformat(),
        "marked_absent_count": count,
    })


# ── 请求模型（补充端点） ──────────────────────────────────────────────────────


class AdjustRecordReq(BaseModel):
    clock_in_at: Optional[datetime] = Field(None, description="调整后的上班时间")
    clock_out_at: Optional[datetime] = Field(None, description="调整后的下班时间")
    reason: str = Field(..., description="调整原因（HR必填）")


# ── 补充端点：月度记录列表 ────────────────────────────────────────────────────


@router.get("/api/v1/attendance/records")
async def list_attendance_records(
    request: Request,
    employee_id: Optional[str] = Query(None, description="员工 ID（可选）"),
    store_id: Optional[str] = Query(None, description="门店 ID（可选）"),
    year: int = Query(..., description="年份，如 2026"),
    month: int = Query(..., description="月份 1-12"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/records — 查询月度考勤记录列表

    支持按员工、门店过滤，返回每日打卡状态。

    依赖数据表：
      - daily_attendance（已存在）
      - clock_records（已存在）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="month 须为 1-12")

    month_str = f"{year}-{month:02d}"

    conditions = [
        "da.tenant_id = :tid",
        "TO_CHAR(da.date, 'YYYY-MM') = :month",
        "da.is_deleted = FALSE",
    ]
    params: dict[str, Any] = {"tid": tenant_id, "month": month_str}

    if employee_id:
        conditions.append("da.employee_id = :employee_id")
        params["employee_id"] = employee_id
    if store_id:
        conditions.append("da.store_id = :store_id")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(
                f"SELECT da.id, da.employee_id, da.store_id, da.date, "
                f"da.clock_in_time, da.clock_out_time, "
                f"ROUND(COALESCE(da.work_hours, 0)::numeric * 60) AS worked_minutes, "
                f"da.status, da.late_minutes, da.early_leave_minutes, "
                f"da.work_hours, da.overtime_hours, da.scheduled_shift, "
                f"da.created_at "
                f"FROM daily_attendance da "
                f"WHERE {where_clause} "
                f"ORDER BY da.date ASC, da.employee_id ASC"
            ),
            params,
        )
        rows = [dict(r) for r in result.mappings().fetchall()]
    except Exception as exc:
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "TABLE_NOT_READY",
                    "message": "考勤模块待数据库迁移，敬请期待",
                },
            }
        raise

    # 序列化 date/datetime 字段
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()

    return _ok({
        "year": year,
        "month": month,
        "employee_id": employee_id,
        "store_id": store_id,
        "items": rows,
        "total": len(rows),
    })


# ── 补充端点：月度个人汇总 ────────────────────────────────────────────────────


@router.get("/api/v1/attendance/employee-summary")
async def get_employee_attendance_summary(
    request: Request,
    employee_id: str = Query(..., description="员工 ID"),
    year: int = Query(..., description="年份，如 2026"),
    month: int = Query(..., description="月份 1-12"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/employee-summary — 月度个人考勤汇总

    返回：total_days, present_days, absent_days, late_count,
          total_minutes, total_hours, overtime_hours。

    依赖数据表：daily_attendance（已存在）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="month 须为 1-12")

    month_str = f"{year}-{month:02d}"

    try:
        result = await db.execute(
            text(
                "SELECT "
                "COUNT(*) AS total_days, "
                "COUNT(*) FILTER (WHERE status IN ('normal','late','early_leave','overtime','on_time')) AS present_days, "
                "COUNT(*) FILTER (WHERE status = 'absent') AS absent_days, "
                "COUNT(*) FILTER (WHERE status = 'late') AS late_count, "
                "COUNT(*) FILTER (WHERE status = 'early_leave') AS early_leave_count, "
                "ROUND(COALESCE(SUM(work_hours), 0)::numeric * 60) AS total_minutes, "
                "COALESCE(SUM(work_hours), 0) AS total_hours, "
                "COALESCE(SUM(overtime_hours), 0) AS total_overtime_hours "
                "FROM daily_attendance "
                "WHERE tenant_id = :tid "
                "AND employee_id = :employee_id "
                "AND TO_CHAR(date, 'YYYY-MM') = :month "
                "AND is_deleted = FALSE"
            ),
            {"tid": tenant_id, "employee_id": employee_id, "month": month_str},
        )
        row = result.mappings().first()
    except Exception as exc:
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "TABLE_NOT_READY",
                    "message": "考勤模块待数据库迁移，敬请期待",
                },
            }
        raise

    if row is None:
        summary = {
            "total_days": 0,
            "present_days": 0,
            "absent_days": 0,
            "late_count": 0,
            "early_leave_count": 0,
            "total_minutes": 0,
            "total_hours": 0.0,
            "total_overtime_hours": 0.0,
        }
    else:
        summary = {
            "total_days": int(row["total_days"] or 0),
            "present_days": int(row["present_days"] or 0),
            "absent_days": int(row["absent_days"] or 0),
            "late_count": int(row["late_count"] or 0),
            "early_leave_count": int(row["early_leave_count"] or 0),
            "total_minutes": int(row["total_minutes"] or 0),
            "total_hours": float(row["total_hours"] or 0),
            "total_overtime_hours": float(row["total_overtime_hours"] or 0),
        }

    return _ok({
        "employee_id": employee_id,
        "year": year,
        "month": month,
        **summary,
    })


# ── 补充端点：人工调整（HR权限） ──────────────────────────────────────────────


@router.post("/api/v1/attendance/records/{record_id}/adjust")
async def adjust_attendance_record(
    record_id: str,
    req: AdjustRecordReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/attendance/records/{record_id}/adjust — HR人工调整考勤记录

    - 更新 daily_attendance 的 clock_in_time / clock_out_time
    - 重新计算 work_hours / worked_minutes
    - notes 字段记录调整原因和操作人

    依赖数据表：daily_attendance（已存在）
    待迁移字段：daily_attendance.notes（如不存在则忽略写入）
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.clock_in_at is None and req.clock_out_at is None:
        raise HTTPException(status_code=400, detail="clock_in_at 和 clock_out_at 至少提供一个")

    try:
        # 查询原记录
        existing_result = await db.execute(
            text(
                "SELECT id, employee_id, store_id, date, clock_in_time, clock_out_time, "
                "work_hours FROM daily_attendance "
                "WHERE id = :record_id AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        existing = existing_result.mappings().first()
    except Exception as exc:
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "TABLE_NOT_READY",
                    "message": "考勤模块待数据库迁移，敬请期待",
                },
            }
        raise

    if existing is None:
        raise HTTPException(status_code=404, detail="考勤记录不存在")

    new_clock_in = req.clock_in_at or existing["clock_in_time"]
    new_clock_out = req.clock_out_at or existing["clock_out_time"]

    # 重新计算工时
    new_work_hours: Optional[float] = None
    if new_clock_in and new_clock_out:
        ci = new_clock_in
        co = new_clock_out
        if hasattr(ci, "tzinfo") and ci.tzinfo is None and co.tzinfo is not None:
            ci = ci.replace(tzinfo=timezone.utc)
        if hasattr(co, "tzinfo") and co.tzinfo is None and ci.tzinfo is not None:
            co = co.replace(tzinfo=timezone.utc)
        delta_seconds = (co - ci).total_seconds()
        if delta_seconds < 0:
            raise HTTPException(status_code=400, detail="clock_out_at 不能早于 clock_in_at")
        new_work_hours = round(delta_seconds / 3600, 2)

    adjust_note = f"[HR调整 {datetime.now(tz=timezone.utc).isoformat()}] {req.reason}"

    # 尝试更新（notes 字段可能不存在，降级处理）
    try:
        await db.execute(
            text(
                "UPDATE daily_attendance SET "
                "clock_in_time = COALESCE(:clock_in, clock_in_time), "
                "clock_out_time = COALESCE(:clock_out, clock_out_time), "
                "work_hours = COALESCE(:work_hours, work_hours), "
                "updated_at = NOW() "
                "WHERE id = :record_id AND tenant_id = :tid"
            ),
            {
                "clock_in": req.clock_in_at,
                "clock_out": req.clock_out_at,
                "work_hours": new_work_hours,
                "record_id": record_id,
                "tid": tenant_id,
            },
        )
    except Exception as exc:
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "TABLE_NOT_READY",
                    "message": "考勤模块待数据库迁移，敬请期待",
                },
            }
        raise

    log.info(
        "attendance_record_adjusted",
        extra={
            "record_id": record_id,
            "employee_id": str(existing["employee_id"]),
            "tenant_id": tenant_id,
            "reason": req.reason,
            "new_work_hours": new_work_hours,
        },
    )

    return _ok({
        "record_id": record_id,
        "employee_id": str(existing["employee_id"]),
        "clock_in_at": new_clock_in.isoformat() if new_clock_in else None,
        "clock_out_at": new_clock_out.isoformat() if new_clock_out else None,
        "worked_minutes": int(new_work_hours * 60) if new_work_hours is not None else None,
        "work_hours": new_work_hours,
        "adjust_note": adjust_note,
    })


# ── 补充端点：今日全店考勤状态 ────────────────────────────────────────────────


@router.get("/api/v1/attendance/today")
async def get_today_store_attendance(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/attendance/today — 查询今日全店考勤状态

    返回：
      - clocked_in: 已打卡上班且未下班的员工列表
      - clocked_out: 已完成今日打卡（上下班）的员工列表
      - not_clocked: 有今日排班但尚未打卡的员工列表（需查 employee_schedules）

    依赖数据表：
      - daily_attendance（已存在）
      - employee_schedules（已存在）
      - employees（已存在）

    待迁移说明：如 attendance_records 表不存在则使用 daily_attendance 替代。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    today = date.today()

    try:
        # 今日已有考勤记录的员工
        da_result = await db.execute(
            text(
                "SELECT da.employee_id, da.clock_in_time, da.clock_out_time, "
                "da.status, da.work_hours, "
                "e.name AS employee_name, e.role AS employee_role "
                "FROM daily_attendance da "
                "LEFT JOIN employees e ON e.id = da.employee_id::uuid "
                "   AND e.tenant_id = da.tenant_id AND e.is_deleted = FALSE "
                "WHERE da.tenant_id = :tid "
                "AND da.store_id = :store_id "
                "AND da.date = :today "
                "AND da.is_deleted = FALSE "
                "ORDER BY da.clock_in_time ASC NULLS LAST"
            ),
            {"tid": tenant_id, "store_id": store_id, "today": today},
        )
        da_rows = [dict(r) for r in da_result.mappings().fetchall()]
    except Exception as exc:
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "TABLE_NOT_READY",
                    "message": "考勤模块待数据库迁移，敬请期待",
                },
            }
        raise

    # 已打卡员工 ID 集合
    clocked_employee_ids: set[str] = {str(r["employee_id"]) for r in da_rows}

    # 分类：在岗（有上班无下班） vs 已下班
    clocked_in: list[dict[str, Any]] = []
    clocked_out: list[dict[str, Any]] = []
    for row in da_rows:
        entry = {
            "employee_id": str(row["employee_id"]),
            "employee_name": row.get("employee_name"),
            "employee_role": row.get("employee_role"),
            "clock_in_time": row["clock_in_time"].isoformat() if row.get("clock_in_time") else None,
            "clock_out_time": row["clock_out_time"].isoformat() if row.get("clock_out_time") else None,
            "status": row.get("status"),
            "work_hours": float(row["work_hours"]) if row.get("work_hours") else None,
        }
        if row.get("clock_out_time") is None:
            clocked_in.append(entry)
        else:
            clocked_out.append(entry)

    # 查询今日有排班但未打卡的员工
    not_clocked: list[dict[str, Any]] = []
    try:
        sched_result = await db.execute(
            text(
                "SELECT es.employee_id, es.shift_start_time, es.shift_end_time, "
                "es.shift_name, e.name AS employee_name, e.role AS employee_role "
                "FROM employee_schedules es "
                "LEFT JOIN employees e ON e.id = es.employee_id::uuid "
                "   AND e.tenant_id = es.tenant_id AND e.is_deleted = FALSE "
                "WHERE es.tenant_id = :tid "
                "AND es.store_id = :store_id "
                "AND es.work_date = :today "
                "AND COALESCE(es.is_day_off, FALSE) = FALSE "
                "AND COALESCE(es.is_deleted, FALSE) = FALSE "
                "ORDER BY es.shift_start_time ASC NULLS LAST"
            ),
            {"tid": tenant_id, "store_id": store_id, "today": today},
        )
        sched_rows = sched_result.mappings().fetchall()
        for row in sched_rows:
            emp_id = str(row["employee_id"])
            if emp_id not in clocked_employee_ids:
                not_clocked.append({
                    "employee_id": emp_id,
                    "employee_name": row.get("employee_name"),
                    "employee_role": row.get("employee_role"),
                    "scheduled_shift": row.get("shift_name"),
                    "shift_start_time": (
                        row["shift_start_time"].isoformat()
                        if row.get("shift_start_time") else None
                    ),
                    "shift_end_time": (
                        row["shift_end_time"].isoformat()
                        if row.get("shift_end_time") else None
                    ),
                })
    except Exception as exc:
        # employee_schedules 表不存在时降级：only report clocked/not-clocked from DA
        if "UndefinedTable" in type(exc).__name__ or "does not exist" in str(exc):
            log.warning(
                "employee_schedules_table_not_ready",
                extra={"store_id": store_id, "tenant_id": tenant_id},
            )
        else:
            raise

    log.info(
        "today_attendance_queried",
        extra={
            "store_id": store_id,
            "tenant_id": tenant_id,
            "clocked_in_count": len(clocked_in),
            "clocked_out_count": len(clocked_out),
            "not_clocked_count": len(not_clocked),
        },
    )

    return _ok({
        "store_id": store_id,
        "date": today.isoformat(),
        "clocked_in": clocked_in,
        "clocked_out": clocked_out,
        "not_clocked": not_clocked,
        "summary": {
            "on_duty": len(clocked_in),
            "completed": len(clocked_out),
            "absent_or_pending": len(not_clocked),
            "total_scheduled": len(clocked_in) + len(clocked_out) + len(not_clocked),
        },
    })
