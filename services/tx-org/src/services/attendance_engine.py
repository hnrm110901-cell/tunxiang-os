"""考勤引擎 — V1迁入(635行) → V3

打卡 + 迟到/早退检测 + 加班记录 + 排班联动 + 请假管理

与 SmartScheduleService 联动：根据排班判定打卡状态。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from shared.events import UniversalPublisher, OrgEventType

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 迟到/早退宽限分钟
GRACE_PERIOD_MINUTES = 5

# 打卡方式
CLOCK_METHODS = {"device", "face", "app", "manual"}

# 请假类型与默认额度（天/年）
LEAVE_TYPES: Dict[str, Dict[str, Any]] = {
    "annual": {"label": "年假", "default_days": 5, "paid": True},
    "sick": {"label": "病假", "default_days": 15, "paid": True},  # 带薪（打折）
    "personal": {"label": "事假", "default_days": 10, "paid": False},
    "maternity": {"label": "产假", "default_days": 158, "paid": True},  # 湖南省158天
    "paternity": {"label": "陪产假", "default_days": 20, "paid": True},  # 湖南省20天
    "marriage": {"label": "婚假", "default_days": 3, "paid": True},
    "bereavement": {"label": "丧假", "default_days": 3, "paid": True},
}

# 加班类型及倍率
OVERTIME_RATES: Dict[str, float] = {
    "weekday": 1.5,
    "weekend": 2.0,
    "holiday": 3.0,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  班次时间映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHIFT_TIMES: Dict[str, Dict[str, time]] = {
    "morning": {"start": time(8, 0), "end": time(15, 0)},
    "middle": {"start": time(11, 0), "end": time(19, 0)},
    "evening": {"start": time(15, 0), "end": time(22, 0)},
    "full": {"start": time(9, 0), "end": time(21, 0)},
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AttendanceEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AttendanceEngine:
    """考勤引擎 — 打卡+迟到/早退+加班+排班联动"""

    def __init__(
        self,
        scheduled_shifts: Optional[Dict[str, Dict[str, str]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            scheduled_shifts: {employee_id: {date_iso: shift_name}}
                排班数据，用于判定迟到/早退
            tenant_id: 租户 UUID 字符串，用于事件发布（可选）
        """
        self.scheduled_shifts = scheduled_shifts or {}
        self.tenant_id = tenant_id
        self._clock_records: List[Dict[str, Any]] = []
        self._clock_counter = 0
        self._leave_requests: List[Dict[str, Any]] = []
        self._leave_counter = 0
        self._overtime_records: List[Dict[str, Any]] = []
        self._overtime_counter = 0
        self._leave_balances: Dict[str, Dict[str, float]] = {}

    # ──────────────────────────────────────────────────────
    #  初始化假期余额
    # ──────────────────────────────────────────────────────

    def init_leave_balance(self, employee_id: str, year: int = 2026) -> Dict[str, float]:
        """初始化员工年度假期余额"""
        balance: Dict[str, float] = {}
        for leave_type, info in LEAVE_TYPES.items():
            balance[leave_type] = float(info["default_days"])
        self._leave_balances[employee_id] = balance
        return balance

    # ──────────────────────────────────────────────────────
    #  Clock In / Out
    # ──────────────────────────────────────────────────────

    def clock_in(
        self,
        employee_id: str,
        store_id: str,
        clock_time: Optional[datetime] = None,
        method: str = "device",
    ) -> Dict[str, Any]:
        """打卡上班

        method: device/face/app/manual
        Auto-detect: on_time / late / early (vs scheduled shift)
        Returns: {clock_id, status, scheduled_start, actual_start, diff_min}
        """
        if method not in CLOCK_METHODS:
            return {"ok": False, "error": f"Invalid method: {method}"}

        now = clock_time or datetime.now()
        date_str = now.date().isoformat()

        # Find scheduled shift
        emp_schedule = self.scheduled_shifts.get(employee_id, {})
        shift_name = emp_schedule.get(date_str)
        scheduled_start = None
        status = "on_time"
        diff_min = 0

        if shift_name and shift_name in SHIFT_TIMES:
            shift_start = SHIFT_TIMES[shift_name]["start"]
            scheduled_start = datetime.combine(now.date(), shift_start)

            diff_seconds = (now - scheduled_start).total_seconds()
            diff_min = int(diff_seconds / 60)

            if diff_min > GRACE_PERIOD_MINUTES:
                status = "late"
            elif diff_min < -30:
                status = "early"  # 提前半小时以上到达
            else:
                status = "on_time"
        else:
            status = "unscheduled"

        self._clock_counter += 1
        clock_id = f"CLK-{self._clock_counter:06d}"

        record = {
            "clock_id": clock_id,
            "employee_id": employee_id,
            "store_id": store_id,
            "date": date_str,
            "clock_type": "in",
            "clock_time": now.isoformat(),
            "method": method,
            "scheduled_shift": shift_name,
            "scheduled_start": scheduled_start.isoformat() if scheduled_start else None,
            "actual_start": now.isoformat(),
            "status": status,
            "diff_min": diff_min,
            "clock_out_time": None,
            "clock_out_status": None,
            "work_hours": None,
        }

        self._clock_records.append(record)

        if status == "late" and diff_min > 0 and self.tenant_id:
            asyncio.create_task(UniversalPublisher.publish(
                event_type=OrgEventType.ATTENDANCE_LATE,
                tenant_id=self.tenant_id,
                store_id=store_id,
                entity_id=employee_id,
                event_data={"employee_id": employee_id, "late_minutes": diff_min, "schedule_id": shift_name},
                source_service="tx-org",
                extra_fields={"employee_id": employee_id},
            ))

        return {
            "ok": True,
            "clock_id": clock_id,
            "status": status,
            "scheduled_start": scheduled_start.isoformat() if scheduled_start else None,
            "actual_start": now.isoformat(),
            "diff_min": diff_min,
            "method": method,
        }

    def clock_out(
        self,
        employee_id: str,
        store_id: str,
        clock_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """打卡下班

        Auto-detect: on_time / early_leave / overtime
        """
        now = clock_time or datetime.now()
        date_str = now.date().isoformat()

        # Find the clock-in record for today
        in_record = None
        for rec in reversed(self._clock_records):
            if (
                rec["employee_id"] == employee_id
                and rec["date"] == date_str
                and rec["clock_type"] == "in"
                and rec["clock_out_time"] is None
            ):
                in_record = rec
                break

        if not in_record:
            return {"ok": False, "error": "No open clock-in record found for today"}

        # Find scheduled shift end
        shift_name = in_record.get("scheduled_shift")
        scheduled_end = None
        status = "on_time"
        diff_min = 0

        if shift_name and shift_name in SHIFT_TIMES:
            shift_end = SHIFT_TIMES[shift_name]["end"]
            scheduled_end = datetime.combine(now.date(), shift_end)

            diff_seconds = (now - scheduled_end).total_seconds()
            diff_min = int(diff_seconds / 60)

            if diff_min < -GRACE_PERIOD_MINUTES:
                status = "early_leave"
            elif diff_min > 30:
                status = "overtime"
            else:
                status = "on_time"
        else:
            status = "unscheduled"

        # Calculate work hours
        clock_in_time = datetime.fromisoformat(in_record["actual_start"])
        work_seconds = (now - clock_in_time).total_seconds()
        work_hours = round(work_seconds / 3600, 2)

        # Update the in record
        in_record["clock_out_time"] = now.isoformat()
        in_record["clock_out_status"] = status
        in_record["work_hours"] = work_hours

        # Create out record
        self._clock_counter += 1
        out_clock_id = f"CLK-{self._clock_counter:06d}"

        out_record = {
            "clock_id": out_clock_id,
            "employee_id": employee_id,
            "store_id": store_id,
            "date": date_str,
            "clock_type": "out",
            "clock_time": now.isoformat(),
            "method": in_record["method"],
            "scheduled_shift": shift_name,
            "scheduled_end": scheduled_end.isoformat() if scheduled_end else None,
            "actual_end": now.isoformat(),
            "status": status,
            "diff_min": diff_min,
            "paired_clock_id": in_record["clock_id"],
            "work_hours": work_hours,
        }
        self._clock_records.append(out_record)

        return {
            "ok": True,
            "clock_id": out_clock_id,
            "paired_clock_in": in_record["clock_id"],
            "status": status,
            "scheduled_end": scheduled_end.isoformat() if scheduled_end else None,
            "actual_end": now.isoformat(),
            "diff_min": diff_min,
            "work_hours": work_hours,
        }

    # ──────────────────────────────────────────────────────
    #  Daily / Monthly Summary
    # ──────────────────────────────────────────────────────

    def get_daily_attendance(
        self,
        store_id: str,
        target_date: date,
    ) -> List[Dict[str, Any]]:
        """当日全员考勤

        All employees: scheduled, clocked_in, clocked_out, status, work_hours
        """
        date_str = target_date.isoformat()
        results: List[Dict[str, Any]] = []

        # Group clock records by employee
        emp_records: Dict[str, List[Dict]] = {}
        for rec in self._clock_records:
            if rec["date"] == date_str and rec["store_id"] == store_id:
                eid = rec["employee_id"]
                if eid not in emp_records:
                    emp_records[eid] = []
                emp_records[eid].append(rec)

        # Build report
        all_employees = set()
        for eid, shifts in self.scheduled_shifts.items():
            if date_str in shifts:
                all_employees.add(eid)
        for eid in emp_records:
            all_employees.add(eid)

        for eid in sorted(all_employees):
            scheduled_shift = self.scheduled_shifts.get(eid, {}).get(date_str)
            records = emp_records.get(eid, [])

            in_rec = next((r for r in records if r["clock_type"] == "in"), None)
            out_rec = next((r for r in records if r["clock_type"] == "out"), None)

            clocked_in = in_rec is not None
            clocked_out = out_rec is not None
            work_hours = in_rec.get("work_hours") if in_rec else None

            # Determine overall status
            if scheduled_shift and not clocked_in:
                overall_status = "absent"
            elif in_rec and in_rec.get("status") == "late":
                overall_status = "late"
            elif out_rec and out_rec.get("status") == "early_leave":
                overall_status = "early_leave"
            elif out_rec and out_rec.get("status") == "overtime":
                overall_status = "overtime"
            elif clocked_in and clocked_out:
                overall_status = "normal"
            elif clocked_in and not clocked_out:
                overall_status = "missing_clock_out"
            elif not scheduled_shift and clocked_in:
                overall_status = "unscheduled"
            else:
                overall_status = "day_off"

            # Check if on leave
            on_leave = self._check_leave(eid, target_date)
            if on_leave:
                overall_status = f"on_leave:{on_leave['leave_type']}"

            results.append({
                "employee_id": eid,
                "date": date_str,
                "scheduled_shift": scheduled_shift,
                "clocked_in": clocked_in,
                "clock_in_time": in_rec.get("actual_start") if in_rec else None,
                "clock_in_status": in_rec.get("status") if in_rec else None,
                "clocked_out": clocked_out,
                "clock_out_time": out_rec.get("actual_end") if out_rec else None,
                "clock_out_status": out_rec.get("status") if out_rec else None,
                "work_hours": work_hours,
                "status": overall_status,
                "on_leave": on_leave,
            })

        return results

    def _check_leave(self, employee_id: str, target_date: date) -> Optional[Dict]:
        """检查员工当天是否有已批准的假"""
        for req in self._leave_requests:
            if (
                req["employee_id"] == employee_id
                and req["status"] == "approved"
                and req["start_date"] <= target_date.isoformat()
                and req["end_date"] >= target_date.isoformat()
            ):
                return {
                    "leave_id": req["leave_id"],
                    "leave_type": req["leave_type"],
                }
        return None

    def get_monthly_summary(
        self,
        employee_id: str,
        month: str,
    ) -> Dict[str, Any]:
        """月度考勤汇总

        work_days, late_count, early_leave_count, absent_count, overtime_hours,
        total_work_hours, attendance_rate

        Args:
            employee_id: 员工ID
            month: "YYYY-MM"
        """
        work_days = 0
        late_count = 0
        early_leave_count = 0
        absent_dates: List[str] = []
        total_work_hours = 0.0
        overtime_hours = 0.0

        # Gather all clock-in records for this employee/month
        in_records = [
            r for r in self._clock_records
            if r["employee_id"] == employee_id
            and r["date"].startswith(month)
            and r["clock_type"] == "in"
        ]

        seen_dates: set = set()
        for rec in in_records:
            d = rec["date"]
            if d not in seen_dates:
                seen_dates.add(d)
                work_days += 1

            if rec.get("status") == "late":
                late_count += 1

            wh = rec.get("work_hours")
            if wh and isinstance(wh, (int, float)):
                total_work_hours += wh

        # Out records for early_leave / overtime
        out_records = [
            r for r in self._clock_records
            if r["employee_id"] == employee_id
            and r["date"].startswith(month)
            and r["clock_type"] == "out"
        ]

        for rec in out_records:
            if rec.get("status") == "early_leave":
                early_leave_count += 1
            elif rec.get("status") == "overtime":
                # Estimate overtime from diff_min
                ot_min = max(0, rec.get("diff_min", 0))
                overtime_hours += ot_min / 60

        # Calculate absences: scheduled but not clocked in
        emp_schedule = self.scheduled_shifts.get(employee_id, {})
        for date_str, shift in emp_schedule.items():
            if not date_str.startswith(month):
                continue
            if date_str not in seen_dates:
                # Check if on leave
                d = date.fromisoformat(date_str)
                leave = self._check_leave(employee_id, d)
                if not leave:
                    absent_dates.append(date_str)

        absent_count = len(absent_dates)

        # Scheduled days for attendance rate
        scheduled_days = sum(
            1 for d, s in emp_schedule.items() if d.startswith(month)
        )
        attendance_rate = 0.0
        if scheduled_days > 0:
            attendance_rate = round(
                (scheduled_days - absent_count) / scheduled_days * 100, 1
            )

        return {
            "employee_id": employee_id,
            "month": month,
            "work_days": work_days,
            "scheduled_days": scheduled_days,
            "late_count": late_count,
            "early_leave_count": early_leave_count,
            "absent_count": absent_count,
            "absent_dates": absent_dates,
            "overtime_hours": round(overtime_hours, 1),
            "total_work_hours": round(total_work_hours, 1),
            "attendance_rate": attendance_rate,
        }

    # ──────────────────────────────────────────────────────
    #  Leave Management (请假)
    # ──────────────────────────────────────────────────────

    def apply_leave(
        self,
        employee_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
    ) -> Dict[str, Any]:
        """申请请假

        leave_type: annual/sick/personal/maternity/paternity/marriage/bereavement
        """
        if leave_type not in LEAVE_TYPES:
            return {"ok": False, "error": f"Invalid leave type: {leave_type}"}

        # Check balance
        balance = self._leave_balances.get(employee_id)
        if not balance:
            balance = self.init_leave_balance(employee_id)

        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
        days_requested = (ed - sd).days + 1

        if days_requested <= 0:
            return {"ok": False, "error": "End date must be after start date"}

        remaining = balance.get(leave_type, 0)
        if days_requested > remaining:
            return {
                "ok": False,
                "error": f"Insufficient {leave_type} balance: {remaining} days remaining, {days_requested} requested",
            }

        self._leave_counter += 1
        leave_id = f"LEV-{self._leave_counter:06d}"

        request = {
            "leave_id": leave_id,
            "employee_id": employee_id,
            "leave_type": leave_type,
            "leave_label": LEAVE_TYPES[leave_type]["label"],
            "start_date": start_date,
            "end_date": end_date,
            "days_requested": days_requested,
            "reason": reason,
            "status": "pending",
            "approved_by": None,
            "created_at": datetime.now().isoformat(),
        }
        self._leave_requests.append(request)

        return {
            "ok": True,
            "leave_id": leave_id,
            "leave_type": leave_type,
            "days_requested": days_requested,
            "remaining_after": remaining - days_requested,
            "status": "pending",
        }

    def approve_leave(
        self,
        leave_id: str,
        approved_by: str,
        approved: bool = True,
    ) -> Dict[str, Any]:
        """审批请假"""
        req = next(
            (r for r in self._leave_requests if r["leave_id"] == leave_id),
            None,
        )
        if not req:
            return {"ok": False, "error": f"Leave request {leave_id} not found"}

        if req["status"] != "pending":
            return {"ok": False, "error": f"Leave request is already {req['status']}"}

        if approved:
            req["status"] = "approved"
            req["approved_by"] = approved_by
            # Deduct from balance
            emp_balance = self._leave_balances.get(req["employee_id"], {})
            lt = req["leave_type"]
            emp_balance[lt] = max(0, emp_balance.get(lt, 0) - req["days_requested"])
        else:
            req["status"] = "rejected"
            req["approved_by"] = approved_by

        return {
            "ok": True,
            "leave_id": leave_id,
            "status": req["status"],
            "approved_by": approved_by,
        }

    def get_leave_balance(self, employee_id: str) -> Dict[str, Any]:
        """查询假期余额"""
        balance = self._leave_balances.get(employee_id)
        if not balance:
            balance = self.init_leave_balance(employee_id)

        items: List[Dict[str, Any]] = []
        for lt, days in balance.items():
            info = LEAVE_TYPES.get(lt, {})
            items.append({
                "leave_type": lt,
                "label": info.get("label", lt),
                "total_days": info.get("default_days", 0),
                "remaining_days": days,
                "used_days": info.get("default_days", 0) - days,
                "paid": info.get("paid", False),
            })

        return {
            "employee_id": employee_id,
            "year": 2026,
            "balances": items,
        }

    # ──────────────────────────────────────────────────────
    #  Overtime
    # ──────────────────────────────────────────────────────

    def record_overtime(
        self,
        employee_id: str,
        target_date: str,
        hours: float,
        reason: str,
        approved_by: str,
        overtime_type: str = "weekday",
    ) -> Dict[str, Any]:
        """记录加班

        Args:
            overtime_type: weekday(1.5x) / weekend(2.0x) / holiday(3.0x)
        """
        if overtime_type not in OVERTIME_RATES:
            return {"ok": False, "error": f"Invalid overtime type: {overtime_type}"}

        if hours <= 0 or hours > 12:
            return {"ok": False, "error": "Overtime hours must be between 0 and 12"}

        rate = OVERTIME_RATES[overtime_type]

        self._overtime_counter += 1
        ot_id = f"OT-{self._overtime_counter:06d}"

        record = {
            "overtime_id": ot_id,
            "employee_id": employee_id,
            "date": target_date,
            "hours": hours,
            "overtime_type": overtime_type,
            "rate": rate,
            "reason": reason,
            "approved_by": approved_by,
            "created_at": datetime.now().isoformat(),
        }
        self._overtime_records.append(record)

        return {
            "ok": True,
            "overtime_id": ot_id,
            "hours": hours,
            "overtime_type": overtime_type,
            "rate": rate,
        }

    # ──────────────────────────────────────────────────────
    #  Anomaly Detection
    # ──────────────────────────────────────────────────────

    def get_attendance_anomalies(
        self,
        store_id: str,
        target_date: date,
    ) -> List[Dict[str, Any]]:
        """考勤异常检测

        Missing clock-in/out, scheduled but absent, unscheduled overtime
        """
        date_str = target_date.isoformat()
        anomalies: List[Dict[str, Any]] = []

        daily = self.get_daily_attendance(store_id, target_date)

        for rec in daily:
            eid = rec["employee_id"]
            status = rec["status"]

            if status == "absent":
                anomalies.append({
                    "employee_id": eid,
                    "date": date_str,
                    "anomaly_type": "absent",
                    "severity": "high",
                    "detail": f"已排班({rec['scheduled_shift']})但未打卡",
                })

            elif status == "missing_clock_out":
                anomalies.append({
                    "employee_id": eid,
                    "date": date_str,
                    "anomaly_type": "missing_clock_out",
                    "severity": "medium",
                    "detail": "已打卡上班但未打卡下班",
                })

            elif status == "late":
                anomalies.append({
                    "employee_id": eid,
                    "date": date_str,
                    "anomaly_type": "late",
                    "severity": "low",
                    "detail": f"迟到（打卡时间: {rec['clock_in_time']}）",
                })

            elif status == "early_leave":
                anomalies.append({
                    "employee_id": eid,
                    "date": date_str,
                    "anomaly_type": "early_leave",
                    "severity": "low",
                    "detail": f"早退（下班打卡: {rec['clock_out_time']}）",
                })

            elif status == "unscheduled":
                anomalies.append({
                    "employee_id": eid,
                    "date": date_str,
                    "anomaly_type": "unscheduled_work",
                    "severity": "medium",
                    "detail": "非排班日但有打卡记录",
                })

        anomalies.sort(
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 9)
        )

        if anomalies and self.tenant_id:
            for anomaly in anomalies:
                if anomaly["anomaly_type"] in ("absent", "missing_clock_out", "unscheduled_work"):
                    asyncio.create_task(UniversalPublisher.publish(
                        event_type=OrgEventType.ATTENDANCE_EXCEPTION,
                        tenant_id=self.tenant_id,
                        store_id=str(store_id),
                        entity_id=anomaly["employee_id"],
                        event_data={"employee_id": anomaly["employee_id"], "exception_type": anomaly["anomaly_type"]},
                        source_service="tx-org",
                        extra_fields={"employee_id": anomaly["employee_id"]},
                    ))

        return anomalies
