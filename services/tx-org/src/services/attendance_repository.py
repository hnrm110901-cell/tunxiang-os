"""考勤数据仓库 — DB-backed Repository

负责：
- clock_records 的读写
- daily_attendance 的 upsert/聚合
- employee_schedules 的查询
- attendance_rules 的查询

所有操作需调用方预先通过 set_config('app.tenant_id', ...) 设置租户上下文（RLS）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# 迟到/加班最低认定分钟（未找到规则时的默认值）
_DEFAULT_GRACE_MINUTES = 5
_DEFAULT_OVERTIME_MIN_MINUTES = 30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  排班查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_employee_schedule(
    employee_id: str,
    work_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询员工指定日期的排班记录"""
    row = await db.execute(
        text(
            "SELECT id, store_id, employee_id, work_date, shift_config_id, "
            "shift_name, shift_start_time, shift_end_time, is_day_off "
            "FROM employee_schedules "
            "WHERE tenant_id = :tid AND employee_id = :eid AND work_date = :wd "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "eid": employee_id, "wd": work_date},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def get_store_schedules_for_date(
    store_id: str,
    work_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询门店指定日期所有员工排班"""
    rows = await db.execute(
        text(
            "SELECT id, store_id, employee_id, work_date, shift_name, "
            "shift_start_time, shift_end_time, is_day_off "
            "FROM employee_schedules "
            "WHERE tenant_id = :tid AND store_id = :sid AND work_date = :wd "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "sid": store_id, "wd": work_date},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  考勤规则查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_attendance_rule(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询门店当前有效的考勤规则"""
    row = await db.execute(
        text(
            "SELECT id, grace_period_minutes, early_leave_grace_minutes, "
            "overtime_min_minutes, late_deduction_fen, early_leave_deduction_fen, "
            "full_attendance_bonus_fen "
            "FROM attendance_rules "
            "WHERE tenant_id = :tid AND store_id = :sid AND is_active = TRUE "
            "AND is_deleted = FALSE "
            "ORDER BY effective_from DESC LIMIT 1"
        ),
        {"tid": tenant_id, "sid": store_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  打卡记录 (clock_records)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_clock_record(
    tenant_id: str,
    store_id: str,
    employee_id: str,
    clock_type: str,
    clock_time: datetime,
    method: str,
    scheduled_shift: Optional[str],
    scheduled_time: Optional[datetime],
    status: str,
    diff_minutes: int,
    device_info: Optional[str],
    location: Optional[str],
    db: AsyncSession,
) -> dict[str, Any]:
    """写入 clock_records"""
    row = await db.execute(
        text(
            "INSERT INTO clock_records "
            "(tenant_id, store_id, employee_id, clock_type, clock_time, method, "
            "scheduled_shift, scheduled_time, status, diff_minutes, device_info, location) "
            "VALUES (:tid, :sid, :eid, :ctype, :ctime, :method, "
            ":sshift, :stime, :status, :diff, :device, :loc) "
            "RETURNING id, employee_id, clock_type, clock_time, status, diff_minutes"
        ),
        {
            "tid": tenant_id,
            "sid": store_id,
            "eid": employee_id,
            "ctype": clock_type,
            "ctime": clock_time,
            "method": method,
            "sshift": scheduled_shift,
            "stime": scheduled_time,
            "status": status,
            "diff": diff_minutes,
            "device": device_info,
            "loc": location,
        },
    )
    await db.commit()
    result = row.mappings().first()
    return dict(result)


async def get_open_clock_in(
    employee_id: str,
    work_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询当天未配对的 clock_in 记录"""
    row = await db.execute(
        text(
            "SELECT id, clock_time, scheduled_shift, scheduled_time, status "
            "FROM clock_records "
            "WHERE tenant_id = :tid AND employee_id = :eid "
            "AND clock_type = 'in' "
            "AND DATE(clock_time AT TIME ZONE 'Asia/Shanghai') = :wd "
            "AND paired_clock_id IS NULL "
            "AND is_deleted = FALSE "
            "ORDER BY clock_time DESC LIMIT 1"
        ),
        {"tid": tenant_id, "eid": employee_id, "wd": work_date},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def update_clock_out_pair(
    clock_in_id: UUID,
    clock_out_id: UUID,
    work_hours: float,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """将 clock_out 记录与对应的 clock_in 关联"""
    await db.execute(
        text(
            "UPDATE clock_records SET paired_clock_id = :out_id, work_hours = :wh, "
            "updated_at = NOW() "
            "WHERE id = :in_id AND tenant_id = :tid"
        ),
        {"out_id": clock_out_id, "wh": work_hours, "in_id": clock_in_id, "tid": tenant_id},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  日考勤聚合 (daily_attendance)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def upsert_daily_attendance(
    tenant_id: str,
    store_id: str,
    employee_id: str,
    work_date: date,
    *,
    clock_in_id: Optional[UUID] = None,
    clock_out_id: Optional[UUID] = None,
    clock_in_time: Optional[datetime] = None,
    clock_out_time: Optional[datetime] = None,
    status: str,
    work_hours: Optional[float] = None,
    overtime_hours: float = 0.0,
    late_minutes: int = 0,
    early_leave_minutes: int = 0,
    scheduled_shift: Optional[str] = None,
    leave_type: Optional[str] = None,
    leave_id: Optional[UUID] = None,
    remark: Optional[str] = None,
    db: AsyncSession,
) -> dict[str, Any]:
    """UPSERT daily_attendance（每员工每天唯一）"""
    row = await db.execute(
        text(
            "INSERT INTO daily_attendance "
            "(tenant_id, store_id, employee_id, date, clock_in_id, clock_out_id, "
            "clock_in_time, clock_out_time, status, work_hours, overtime_hours, "
            "late_minutes, early_leave_minutes, scheduled_shift, leave_type, leave_id, remark) "
            "VALUES (:tid, :sid, :eid, :wd, :in_id, :out_id, "
            ":in_time, :out_time, :status, :wh, :ot, "
            ":late, :early, :sshift, :ltype, :lid, :remark) "
            "ON CONFLICT ON CONSTRAINT uq_daily_attendance_emp_date "
            "DO UPDATE SET "
            "clock_in_id = COALESCE(EXCLUDED.clock_in_id, daily_attendance.clock_in_id), "
            "clock_out_id = COALESCE(EXCLUDED.clock_out_id, daily_attendance.clock_out_id), "
            "clock_in_time = COALESCE(EXCLUDED.clock_in_time, daily_attendance.clock_in_time), "
            "clock_out_time = COALESCE(EXCLUDED.clock_out_time, daily_attendance.clock_out_time), "
            "status = EXCLUDED.status, "
            "work_hours = COALESCE(EXCLUDED.work_hours, daily_attendance.work_hours), "
            "overtime_hours = EXCLUDED.overtime_hours, "
            "late_minutes = EXCLUDED.late_minutes, "
            "early_leave_minutes = EXCLUDED.early_leave_minutes, "
            "scheduled_shift = COALESCE(EXCLUDED.scheduled_shift, daily_attendance.scheduled_shift), "
            "leave_type = COALESCE(EXCLUDED.leave_type, daily_attendance.leave_type), "
            "leave_id = COALESCE(EXCLUDED.leave_id, daily_attendance.leave_id), "
            "remark = COALESCE(EXCLUDED.remark, daily_attendance.remark), "
            "updated_at = NOW() "
            "RETURNING id, employee_id, date, status, work_hours, overtime_hours, "
            "late_minutes, early_leave_minutes"
        ),
        {
            "tid": tenant_id,
            "sid": store_id,
            "eid": employee_id,
            "wd": work_date,
            "in_id": str(clock_in_id) if clock_in_id else None,
            "out_id": str(clock_out_id) if clock_out_id else None,
            "in_time": clock_in_time,
            "out_time": clock_out_time,
            "status": status,
            "wh": work_hours,
            "ot": overtime_hours,
            "late": late_minutes,
            "early": early_leave_minutes,
            "sshift": scheduled_shift,
            "ltype": leave_type,
            "lid": str(leave_id) if leave_id else None,
            "remark": remark,
        },
    )
    await db.commit()
    result = row.mappings().first()
    return dict(result)


async def get_daily_attendance_for_store(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询门店指定日期所有员工的日考勤记录"""
    rows = await db.execute(
        text(
            "SELECT da.id, da.employee_id, da.date, da.scheduled_shift, "
            "da.clock_in_time, da.clock_out_time, da.status, da.work_hours, "
            "da.overtime_hours, da.late_minutes, da.early_leave_minutes, "
            "da.leave_type, da.leave_id "
            "FROM daily_attendance da "
            "WHERE da.tenant_id = :tid AND da.store_id = :sid AND da.date = :wd "
            "AND da.is_deleted = FALSE "
            "ORDER BY da.employee_id"
        ),
        {"tid": tenant_id, "sid": store_id, "wd": target_date},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def get_monthly_attendance_summary(
    employee_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询员工月度考勤记录（所有日期）"""
    rows = await db.execute(
        text(
            "SELECT date, status, work_hours, overtime_hours, "
            "late_minutes, early_leave_minutes, leave_type "
            "FROM daily_attendance "
            "WHERE tenant_id = :tid AND employee_id = :eid "
            "AND TO_CHAR(date, 'YYYY-MM') = :month "
            "AND is_deleted = FALSE "
            "ORDER BY date"
        ),
        {"tid": tenant_id, "eid": employee_id, "month": month},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def get_attendance_anomalies(
    store_id: str,
    start_date: date,
    end_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询考勤异常记录（迟到/早退/旷工/缺卡）"""
    rows = await db.execute(
        text(
            "SELECT employee_id, date, status, late_minutes, early_leave_minutes, "
            "clock_in_time, clock_out_time, scheduled_shift "
            "FROM daily_attendance "
            "WHERE tenant_id = :tid AND store_id = :sid "
            "AND date BETWEEN :sd AND :ed "
            "AND status IN ('late', 'early_leave', 'absent', 'missing_clock_out') "
            "AND is_deleted = FALSE "
            "ORDER BY date DESC, employee_id"
        ),
        {"tid": tenant_id, "sid": store_id, "sd": start_date, "ed": end_date},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def mark_absent_employees(
    store_id: str,
    work_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> int:
    """标记有排班但无打卡且无请假的员工为缺勤

    由定时任务（每天结束后）调用，返回标记数量。
    """
    # 查询有排班但 daily_attendance 为空或 pending 的员工
    scheduled_rows = await db.execute(
        text(
            "SELECT es.employee_id, es.shift_name, es.shift_start_time "
            "FROM employee_schedules es "
            "WHERE es.tenant_id = :tid AND es.store_id = :sid "
            "AND es.work_date = :wd AND es.is_day_off = FALSE "
            "AND es.is_deleted = FALSE "
            "AND es.employee_id NOT IN ("
            "  SELECT employee_id FROM daily_attendance "
            "  WHERE tenant_id = :tid AND store_id = :sid AND date = :wd "
            "  AND status NOT IN ('pending', 'absent') AND is_deleted = FALSE"
            ") "
            "AND es.employee_id NOT IN ("
            "  SELECT lr.employee_id FROM leave_requests lr "
            "  WHERE lr.tenant_id = :tid AND lr.status = 'approved' "
            "  AND lr.start_date <= :wd AND lr.end_date >= :wd "
            "  AND lr.is_deleted = FALSE"
            ")"
        ),
        {"tid": tenant_id, "sid": store_id, "wd": work_date},
    )
    scheduled = scheduled_rows.mappings().fetchall()
    count = 0
    for emp in scheduled:
        await upsert_daily_attendance(
            tenant_id=tenant_id,
            store_id=store_id,
            employee_id=emp["employee_id"],
            work_date=work_date,
            status="absent",
            scheduled_shift=emp.get("shift_name"),
            remark="有排班无打卡，系统自动标记缺勤",
            db=db,
        )
        count += 1
    return count


async def update_daily_attendance_on_leave(
    employee_id: str,
    work_date: date,
    leave_id: UUID,
    leave_type: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """将请假期间的 daily_attendance 状态更新为 on_leave"""
    # 先查是否存在
    existing = await db.execute(
        text(
            "SELECT id FROM daily_attendance "
            "WHERE tenant_id = :tid AND employee_id = :eid AND date = :wd "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "eid": employee_id, "wd": work_date},
    )
    if existing.mappings().first():
        await db.execute(
            text(
                "UPDATE daily_attendance SET status = 'on_leave', "
                "leave_type = :ltype, leave_id = :lid, updated_at = NOW() "
                "WHERE tenant_id = :tid AND employee_id = :eid AND date = :wd"
            ),
            {
                "ltype": leave_type,
                "lid": str(leave_id),
                "tid": tenant_id,
                "eid": employee_id,
                "wd": work_date,
            },
        )
    else:
        # 请假日不一定有打卡记录，插入一条 on_leave 记录
        await upsert_daily_attendance(
            tenant_id=tenant_id,
            store_id=store_id,
            employee_id=employee_id,
            work_date=work_date,
            status="on_leave",
            leave_type=leave_type,
            leave_id=leave_id,
            db=db,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资扣减数据接口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_payroll_attendance_data(
    employee_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
    late_deduction_fen: int = 5000,
) -> dict[str, Any]:
    """为薪资引擎提供月度考勤汇总

    返回：work_days, absent_days, late_times, late_deduction_fen,
          overtime_hours, leave_deduction_fen
    """
    rows = await get_monthly_attendance_summary(employee_id, month, tenant_id, db)

    work_days = 0
    absent_days = 0
    late_times = 0
    overtime_hours = 0.0

    for r in rows:
        status = r["status"]
        if status in ("normal", "late", "early_leave", "overtime"):
            work_days += 1
        elif status == "absent":
            absent_days += 1
        if status == "late":
            late_times += 1
        ot = r.get("overtime_hours") or 0
        overtime_hours += float(ot)

    # 请假扣款：事假/病假（从 leave_requests 查询本月已批准记录）
    leave_rows = await db.execute(
        text(
            "SELECT SUM(deduction_fen) AS total_deduction "
            "FROM leave_requests "
            "WHERE tenant_id = :tid AND employee_id = :eid "
            "AND status = 'approved' "
            "AND TO_CHAR(start_date, 'YYYY-MM') = :month "
            "AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "eid": employee_id, "month": month},
    )
    leave_row = leave_rows.mappings().first()
    leave_deduction_fen = int(leave_row["total_deduction"] or 0)

    return {
        "employee_id": employee_id,
        "month": month,
        "work_days": work_days,
        "absent_days": absent_days,
        "late_times": late_times,
        "late_deduction_fen": late_times * late_deduction_fen,
        "overtime_hours": round(overtime_hours, 2),
        "leave_deduction_fen": leave_deduction_fen,
    }
