"""考勤打卡 API 路由

端点列表：
  POST /api/v1/attendance/clock-in          打卡上班
  POST /api/v1/attendance/clock-out         打卡下班
  GET  /api/v1/attendance/daily             指定日期门店打卡状态
  GET  /api/v1/attendance/summary           月度考勤汇总
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

    if diff > _LATE_MAJOR_THRESHOLD:
        status = "late"
    elif diff > grace_minutes:
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

    return _ok({
        "store_id": store_id,
        "month": month,
        "items": items,
        "total": len(items),
    })


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
