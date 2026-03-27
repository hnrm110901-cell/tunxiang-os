"""Sprint 5-6 运营引擎测试 — 排班/考勤/薪资/损耗

覆盖：
- 客流预测（工作日 vs 周末 vs 节假日）
- 自动排班7天 + 约束校验
- 加班上限违规检测
- 打卡上下班 + 迟到/早退检测
- 月度考勤汇总
- 完整薪资：基本+提成+加班+五险一金+个税=实发
- 个税阶梯计算（验证各级边界）
- 长沙五险一金费率
- 损耗记录 + TOP5 + 根因分析 + 整改跟踪
- 排班效率（预测 vs 实际）
"""

import sys
import os

# ── Setup path BEFORE any local imports ──
_here = os.path.dirname(os.path.abspath(__file__))
for _p in [
    os.path.join(_here, ".."),                          # tx-org/src
    os.path.join(_here, "..", "..", "..", "tx-supply", "src"),  # tx-supply/src
]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

from datetime import date, datetime, timedelta

import pytest

from services.smart_schedule import (
    SmartScheduleService,
    EMPLOYEE_DATABASE,
    SHIFT_DEFINITIONS,
    MAX_CONSECUTIVE_DAYS,
    MAX_OVERTIME_MONTH_HOURS,
    DAY_OF_WEEK_FACTOR,
    HOURLY_DISTRIBUTION,
)
from services.attendance_engine import (
    AttendanceEngine,
    SHIFT_TIMES,
    LEAVE_TYPES,
    GRACE_PERIOD_MINUTES,
)
from services.payroll_service import (
    PayrollService,
    SOCIAL_INSURANCE_RATES,
    EMPLOYEE_SALARY_CONFIG,
    TAX_BRACKETS_YUAN,
    MONTHLY_EXEMPTION_YUAN,
)
import importlib.util as _ilu
_wg_path = os.path.join(_here, "..", "..", "..", "tx-supply", "src", "services", "waste_guard_v2.py")
_wg_spec = _ilu.spec_from_file_location("waste_guard_v2", os.path.abspath(_wg_path))
_wg_mod = _ilu.module_from_spec(_wg_spec)
_wg_spec.loader.exec_module(_wg_mod)
WasteGuardV2 = _wg_mod.WasteGuardV2
WASTE_TYPES = _wg_mod.WASTE_TYPES
ROOT_CAUSE_MAP = _wg_mod.ROOT_CAUSE_MAP
INGREDIENT_NAMES = getattr(_wg_mod, "INGREDIENT_NAMES", {})
INGREDIENT_COST_PER_KG_FEN = getattr(_wg_mod, "INGREDIENT_COST_PER_KG_FEN", {})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STORE_ID = "STORE_CS_001"


@pytest.fixture
def schedule_svc():
    return SmartScheduleService()


@pytest.fixture
def attendance_engine():
    # Set up some scheduled shifts for testing
    schedules = {
        "EMP001": {"2026-03-23": "morning", "2026-03-24": "morning"},
        "EMP002": {"2026-03-23": "middle", "2026-03-24": "evening"},
        "EMP003": {"2026-03-23": "morning"},
        "EMP007": {"2026-03-23": "evening"},
    }
    return AttendanceEngine(scheduled_shifts=schedules)


@pytest.fixture
def payroll_svc():
    return PayrollService()


@pytest.fixture
def waste_guard():
    return WasteGuardV2()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Traffic Prediction Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTrafficPrediction:
    """客流预测测试"""

    def test_weekday_prediction(self, schedule_svc):
        """工作日（周三）客流预测"""
        wed = date(2026, 3, 25)  # Wednesday
        assert wed.weekday() == 2

        hourly = schedule_svc.predict_traffic(STORE_ID, wed)
        assert len(hourly) > 0

        # Weekday factor is 0.90
        total = sum(h["predicted_customers"] for h in hourly)
        assert total > 0
        assert total < 400  # weekday should be moderate

    def test_weekend_prediction(self, schedule_svc):
        """周末客流应高于工作日"""
        wed = date(2026, 3, 25)  # Wednesday
        sat = date(2026, 3, 28)  # Saturday

        weekday_total = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, wed)
        )
        weekend_total = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, sat)
        )
        assert weekend_total > weekday_total

    def test_holiday_prediction(self, schedule_svc):
        """节假日客流应最高"""
        wed = date(2026, 3, 25)

        normal_total = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, wed, holiday_type="normal")
        )
        holiday_total = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, wed, holiday_type="national_day")
        )
        assert holiday_total > normal_total * 1.4  # national_day factor is 1.6

    def test_rainy_day_reduces_traffic(self, schedule_svc):
        """下雨天客流应减少"""
        d = date(2026, 3, 25)

        sunny = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, d, weather="sunny")
        )
        rainy = sum(
            h["predicted_customers"]
            for h in schedule_svc.predict_traffic(STORE_ID, d, weather="rainy")
        )
        assert rainy < sunny

    def test_peak_detection(self, schedule_svc):
        """午高峰和晚高峰检测"""
        d = date(2026, 3, 25)
        hourly = schedule_svc.predict_traffic(STORE_ID, d)

        lunch_peaks = [h for h in hourly if h["is_peak"] and h["peak_type"] == "lunch"]
        dinner_peaks = [h for h in hourly if h["is_peak"] and h["peak_type"] == "dinner"]

        assert len(lunch_peaks) > 0
        assert len(dinner_peaks) > 0

        # Peak hours should have higher traffic
        peak_avg = sum(h["predicted_customers"] for h in lunch_peaks) / len(lunch_peaks)
        all_avg = sum(h["predicted_customers"] for h in hourly) / len(hourly)
        assert peak_avg > all_avg

    def test_shift_granularity(self, schedule_svc):
        """按班次粒度聚合"""
        d = date(2026, 3, 25)
        shifts = schedule_svc.predict_traffic(STORE_ID, d, granularity="shift")

        assert len(shifts) == len(SHIFT_DEFINITIONS)
        for s in shifts:
            assert "shift" in s
            assert "predicted_customers" in s
            assert s["predicted_customers"] > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. Smart Schedule Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSmartSchedule:
    """智能排班测试"""

    def test_generate_7day_schedule(self, schedule_svc):
        """生成7天排班表"""
        start = date(2026, 3, 23)  # Monday
        result = schedule_svc.generate_schedule(STORE_ID, start)

        assert "schedule_id" in result
        assert "schedule" in result
        assert len(result["schedule"]) == 7

        # Each day should have shifts
        for date_str, day_sch in result["schedule"].items():
            assert isinstance(day_sch, dict)
            # At least one shift should have employees
            total_assigned = sum(len(emps) for emps in day_sch.values())
            assert total_assigned > 0, f"No employees assigned on {date_str}"

    def test_schedule_has_validation(self, schedule_svc):
        """排班表包含合规校验结果"""
        start = date(2026, 3, 23)
        result = schedule_svc.generate_schedule(STORE_ID, start)

        assert "validation" in result
        v = result["validation"]
        assert "valid" in v
        assert "violations" in v
        assert isinstance(v["violations"], list)

    def test_skill_matching(self, schedule_svc):
        """技能匹配"""
        matches = schedule_svc.match_skills(
            STORE_ID, "morning", ["chef_hot", "chef_cold"]
        )

        assert len(matches) > 0
        for m in matches:
            assert m["match_score"] > 0
            assert any(
                s in m["skills"]
                for s in ["chef_hot", "chef_cold"]
            )

        # 王强（主厨）should be top match — all chef skills
        chef_names = [m["name"] for m in matches]
        assert "王强" in chef_names

    def test_minor_not_assigned_night(self, schedule_svc):
        """未成年人不应被排到夜班"""
        start = date(2026, 3, 23)
        result = schedule_svc.generate_schedule(STORE_ID, start)

        minor_id = "EMP009"  # 吴浩 is_minor=True
        for date_str, day_sch in result["schedule"].items():
            evening_emps = day_sch.get("evening", [])
            # Evening shift ends at 22:00, which is the cutoff
            assert minor_id not in evening_emps, \
                f"Minor {minor_id} assigned to evening shift on {date_str}"

    def test_staffing_need_calculation(self, schedule_svc):
        """人力需求计算"""
        d = date(2026, 3, 28)  # Saturday
        needs = schedule_svc.calculate_staffing_need(STORE_ID, d)

        assert "hourly_needs" in needs
        assert "total_shifts" in needs
        assert needs["total_shifts"] > 0

        # Peak hour should need more staff
        lunch_peak = needs["peak_staffing"]["lunch_peak"]
        assert lunch_peak.get("waiter", 0) > 0
        assert lunch_peak.get("chef_hot", 0) > 0

    def test_update_shift(self, schedule_svc):
        """更新员工班次"""
        start = date(2026, 3, 23)
        result = schedule_svc.generate_schedule(STORE_ID, start)

        sch_id = result["schedule_id"]
        first_date = list(result["schedule"].keys())[0]

        # Find an employee in morning shift
        morning_emps = result["schedule"][first_date].get("morning", [])
        if morning_emps:
            emp_id = morning_emps[0]
            update = schedule_svc.update_shift(sch_id, emp_id, "evening", first_date)
            assert update["ok"]
            assert update["old_shift"] == "morning"
            assert update["new_shift"] == "evening"

    def test_swap_shift(self, schedule_svc):
        """互换班次"""
        start = date(2026, 3, 23)
        result = schedule_svc.generate_schedule(STORE_ID, start)

        sch_id = result["schedule_id"]
        first_date = list(result["schedule"].keys())[0]

        morning_emps = result["schedule"][first_date].get("morning", [])
        evening_emps = result["schedule"][first_date].get("evening", [])

        if morning_emps and evening_emps:
            swap = schedule_svc.swap_shift(
                sch_id, morning_emps[0], evening_emps[0], first_date
            )
            assert swap["ok"]

    def test_schedule_efficiency(self, schedule_svc):
        """排班效率分析"""
        start = date(2026, 3, 23)
        schedule_svc.generate_schedule(STORE_ID, start)

        end = start + timedelta(days=6)
        actual_traffic = {
            (start + timedelta(days=i)).isoformat(): 250 + i * 10
            for i in range(7)
        }

        efficiency = schedule_svc.get_schedule_efficiency(
            STORE_ID, (start, end), actual_traffic
        )

        assert "total_scheduled_hours" in efficiency
        assert "prediction_accuracy_pct" in efficiency
        assert "efficiency_score" in efficiency
        assert efficiency["total_scheduled_hours"] > 0

    def test_overtime_report(self, schedule_svc):
        """加班报表"""
        start = date(2026, 3, 2)  # Start of month
        schedule_svc.generate_schedule(STORE_ID, start)

        report = schedule_svc.get_overtime_report(STORE_ID, "2026-03")
        assert isinstance(report, list)

        for emp in report:
            assert "overtime_hours" in emp
            assert "exceeds_monthly_cap" in emp
            assert emp["cap_hours"] == MAX_OVERTIME_MONTH_HOURS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. Constraint Validation Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConstraintValidation:
    """劳动法约束校验测试"""

    def test_overtime_cap_detection(self, schedule_svc):
        """检测加班超限"""
        # Create a schedule with excessive overtime
        fake_schedule = {
            "schedule_id": "TEST-OT",
            "store_id": STORE_ID,
            "schedule": {},
            "employee_hours_summary": {
                "EMP001": 55.0,  # Far exceeds 44h
            },
        }

        result = schedule_svc.validate_schedule(fake_schedule)
        assert not result["valid"]

        ot_violations = [
            v for v in result["violations"]
            if v["rule"] == "weekly_hours_cap"
        ]
        assert len(ot_violations) > 0
        assert ot_violations[0]["employee_id"] == "EMP001"

    def test_consecutive_days_detection(self, schedule_svc):
        """检测连续工作天数超限"""
        # Create 8 consecutive days
        start = date(2026, 3, 23)
        schedule = {}
        for i in range(8):
            d = (start + timedelta(days=i)).isoformat()
            schedule[d] = {"morning": ["EMP001"]}

        fake_schedule = {
            "schedule_id": "TEST-CONS",
            "store_id": STORE_ID,
            "schedule": schedule,
            "employee_hours_summary": {"EMP001": 40.0},
        }

        result = schedule_svc.validate_schedule(fake_schedule)

        consec_violations = [
            v for v in result["violations"]
            if v["rule"] == "max_consecutive_days"
        ]
        assert len(consec_violations) > 0

    def test_minor_night_shift_violation(self, schedule_svc):
        """检测未成年夜班违规"""
        fake_schedule = {
            "schedule_id": "TEST-MINOR",
            "store_id": STORE_ID,
            "schedule": {
                "2026-03-23": {"evening": ["EMP009"]},  # EMP009 is minor
            },
            "employee_hours_summary": {"EMP009": 7.0},
        }

        result = schedule_svc.validate_schedule(fake_schedule)

        minor_violations = [
            v for v in result["violations"]
            if v["rule"] == "minor_night_shift"
        ]
        assert len(minor_violations) > 0
        assert minor_violations[0]["employee_id"] == "EMP009"

    def test_valid_schedule_passes(self, schedule_svc):
        """合规排班应通过校验"""
        fake_schedule = {
            "schedule_id": "TEST-OK",
            "store_id": STORE_ID,
            "schedule": {
                "2026-03-23": {"morning": ["EMP001"]},
                "2026-03-24": {"morning": ["EMP001"]},
                "2026-03-25": {"morning": ["EMP001"]},
            },
            "employee_hours_summary": {"EMP001": 21.0},
        }

        result = schedule_svc.validate_schedule(fake_schedule)
        assert result["valid"]
        assert result["error_count"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Attendance Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAttendance:
    """考勤引擎测试"""

    def test_clock_in_on_time(self, attendance_engine):
        """准时打卡"""
        result = attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 0),
            method="face",
        )
        assert result["ok"]
        assert result["status"] == "on_time"
        assert result["diff_min"] == 0

    def test_clock_in_late(self, attendance_engine):
        """迟到打卡（超过宽限期）"""
        result = attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 15),  # 15 min late
        )
        assert result["ok"]
        assert result["status"] == "late"
        assert result["diff_min"] == 15

    def test_clock_in_within_grace(self, attendance_engine):
        """宽限期内打卡不算迟到"""
        result = attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 3),  # 3 min, within grace
        )
        assert result["ok"]
        assert result["status"] == "on_time"

    def test_clock_out_on_time(self, attendance_engine):
        """准时下班打卡"""
        # Clock in first
        attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 0),
        )
        # Clock out
        result = attendance_engine.clock_out(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 15, 0),
        )
        assert result["ok"]
        assert result["status"] == "on_time"
        assert result["work_hours"] == 7.0

    def test_clock_out_early_leave(self, attendance_engine):
        """早退检测"""
        attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 0),
        )
        result = attendance_engine.clock_out(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 14, 0),  # 1 hour early
        )
        assert result["ok"]
        assert result["status"] == "early_leave"

    def test_clock_out_overtime(self, attendance_engine):
        """加班检测"""
        attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 0),
        )
        result = attendance_engine.clock_out(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 16, 0),  # 1 hour overtime
        )
        assert result["ok"]
        assert result["status"] == "overtime"

    def test_daily_attendance(self, attendance_engine):
        """日考勤报表"""
        # EMP001 clocks in on time
        attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 0),
        )
        attendance_engine.clock_out(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 15, 0),
        )

        # EMP003 is scheduled but doesn't clock in (absent)
        daily = attendance_engine.get_daily_attendance(STORE_ID, date(2026, 3, 23))

        assert len(daily) > 0

        emp001_rec = next((r for r in daily if r["employee_id"] == "EMP001"), None)
        assert emp001_rec is not None
        assert emp001_rec["status"] == "normal"
        assert emp001_rec["work_hours"] == 7.0

        emp003_rec = next((r for r in daily if r["employee_id"] == "EMP003"), None)
        assert emp003_rec is not None
        assert emp003_rec["status"] == "absent"

    def test_monthly_summary(self, attendance_engine):
        """月度考勤汇总"""
        # Simulate a few days of attendance
        for day in [23, 24]:
            attendance_engine.clock_in(
                "EMP001", STORE_ID,
                clock_time=datetime(2026, 3, day, 8, 0),
            )
            attendance_engine.clock_out(
                "EMP001", STORE_ID,
                clock_time=datetime(2026, 3, day, 15, 0),
            )

        summary = attendance_engine.get_monthly_summary("EMP001", "2026-03")

        assert summary["work_days"] == 2
        assert summary["late_count"] == 0
        assert summary["total_work_hours"] == 14.0

    def test_leave_application_and_approval(self, attendance_engine):
        """请假申请与审批"""
        attendance_engine.init_leave_balance("EMP007")

        # Apply
        result = attendance_engine.apply_leave(
            "EMP007", "annual", "2026-04-01", "2026-04-03", "家庭事务"
        )
        assert result["ok"]
        assert result["days_requested"] == 3
        assert result["remaining_after"] == 2  # 5 - 3 = 2

        # Approve
        leave_id = result["leave_id"]
        approval = attendance_engine.approve_leave(leave_id, "EMP001")
        assert approval["ok"]
        assert approval["status"] == "approved"

        # Balance should be updated
        balance = attendance_engine.get_leave_balance("EMP007")
        annual = next(
            b for b in balance["balances"] if b["leave_type"] == "annual"
        )
        assert annual["remaining_days"] == 2.0

    def test_leave_insufficient_balance(self, attendance_engine):
        """余额不足应拒绝"""
        attendance_engine.init_leave_balance("EMP008")

        result = attendance_engine.apply_leave(
            "EMP008", "annual", "2026-04-01", "2026-04-15", "长假"
        )
        assert not result["ok"]
        assert "Insufficient" in result["error"]

    def test_attendance_anomalies(self, attendance_engine):
        """考勤异常检测"""
        # EMP001 clocks in late
        attendance_engine.clock_in(
            "EMP001", STORE_ID,
            clock_time=datetime(2026, 3, 23, 8, 20),
        )

        # EMP003 doesn't clock in (scheduled for morning)

        anomalies = attendance_engine.get_attendance_anomalies(STORE_ID, date(2026, 3, 23))

        assert len(anomalies) >= 2  # at least late + absent

        types = [a["anomaly_type"] for a in anomalies]
        assert "absent" in types
        assert "late" in types

    def test_record_overtime(self, attendance_engine):
        """记录加班"""
        result = attendance_engine.record_overtime(
            "EMP003", "2026-03-28", 4.0, "活鱼到货需处理", "EMP001", "weekend"
        )
        assert result["ok"]
        assert result["hours"] == 4.0
        assert result["rate"] == 2.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. Payroll Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPayroll:
    """薪资计算测试"""

    def test_full_payroll_calculation(self, payroll_svc):
        """完整薪资计算：基本+提成+加班+社保+个税=实发"""
        result = payroll_svc.calculate_employee_payroll(
            employee_id="EMP001",
            month="2026-03",
            attendance_data={
                "attendance_days": 22,
                "absence_days": 0,
                "late_count": 0,
                "early_leave_count": 0,
            },
            overtime_data={
                "weekday_hours": 10,
                "weekend_hours": 4,
                "holiday_hours": 0,
            },
            sales_amount_fen=50_000_000,  # 50万营业额
            performance_coefficient=1.2,
            month_index=3,  # March
        )

        assert result["ok"]
        assert result["name"] == "张伟"
        assert result["base_pay_fen"] == 800_000  # Full attendance
        assert result["position_allowance_fen"] == 100_000
        assert result["commission_fen"] > 0  # 50万 * 0.5%
        assert result["overtime_pay_fen"] > 0
        assert result["performance_bonus_fen"] > 0
        assert result["full_attendance_bonus_fen"] == 30_000
        assert result["gross_salary_fen"] > result["net_pay_fen"]
        assert result["net_pay_fen"] > 0
        assert result["social_insurance_employee_fen"] > 0
        assert result["housing_fund_employee_fen"] > 0

    def test_payroll_with_absence(self, payroll_svc):
        """缺勤影响工资"""
        full = payroll_svc.calculate_employee_payroll(
            "EMP007", "2026-03",
            attendance_data={"attendance_days": 22, "absence_days": 0,
                             "late_count": 0, "early_leave_count": 0},
        )
        partial = payroll_svc.calculate_employee_payroll(
            "EMP007", "2026-03",
            attendance_data={"attendance_days": 18, "absence_days": 4,
                             "late_count": 2, "early_leave_count": 1},
        )

        assert full["ok"] and partial["ok"]
        assert partial["net_pay_fen"] < full["net_pay_fen"]
        assert partial["absence_deduction_fen"] > 0
        assert partial["late_deduction_fen"] == 10_000  # 2 * 5000
        assert partial["early_leave_deduction_fen"] == 5_000
        assert partial["full_attendance_bonus_fen"] == 0  # No full attendance

    def test_commission_calculation(self, payroll_svc):
        """提成计算"""
        # EMP007 (waiter) has 0.3% commission
        result = payroll_svc.calculate_employee_payroll(
            "EMP007", "2026-03",
            sales_amount_fen=10_000_000,  # 10万销售额
        )
        assert result["ok"]
        assert result["commission_fen"] == 30_000  # 10万 * 0.3% = 300 yuan

    def test_overtime_pay_rates(self, payroll_svc):
        """加班费倍率：工作日1.5x，周末2x，节假日3x"""
        result = payroll_svc.calculate_employee_payroll(
            "EMP004", "2026-03",
            overtime_data={
                "weekday_hours": 10,
                "weekend_hours": 8,
                "holiday_hours": 8,
            },
        )
        assert result["ok"]
        detail = result["overtime_detail"]

        hourly = detail["hourly_rate_fen"]
        assert detail["weekday_fen"] == int(hourly * 1.5 * 10)
        assert detail["weekend_fen"] == int(hourly * 2.0 * 8)
        assert detail["holiday_fen"] == int(hourly * 3.0 * 8)

    def test_seniority_subsidy(self, payroll_svc):
        """工龄补贴"""
        # EMP003: seniority_months=48 → 200 yuan
        result = payroll_svc.calculate_employee_payroll("EMP003", "2026-03")
        assert result["ok"]
        assert result["seniority_subsidy_fen"] == 20_000  # 200 yuan

        # EMP006: seniority_months=13 → 50 yuan
        result2 = payroll_svc.calculate_employee_payroll("EMP006", "2026-03")
        assert result2["ok"]
        assert result2["seniority_subsidy_fen"] == 5_000  # 50 yuan

    def test_store_payroll_batch(self, payroll_svc):
        """全店薪资批次"""
        result = payroll_svc.calculate_payroll(STORE_ID, "2026-03")

        assert result["batch_id"].startswith("PAY-")
        assert result["employee_count"] == 10
        assert result["status"] == "draft"
        assert result["summary"]["total_gross_fen"] > 0
        assert result["summary"]["total_net_fen"] > 0
        assert result["summary"]["total_labor_cost_fen"] > result["summary"]["total_gross_fen"]

    def test_approve_payroll(self, payroll_svc):
        """审批薪资"""
        batch = payroll_svc.calculate_payroll(STORE_ID, "2026-03")
        batch_id = batch["batch_id"]

        approval = payroll_svc.approve_payroll(batch_id, "boss_001")
        assert approval["ok"]
        assert approval["status"] == "approved"

        # Cannot approve twice
        re_approve = payroll_svc.approve_payroll(batch_id, "boss_001")
        assert not re_approve["ok"]

    def test_payslip_generation(self, payroll_svc):
        """工资条生成"""
        slip = payroll_svc.generate_payslip("EMP001", "2026-03")

        assert slip["name"] == "张伟"
        assert len(slip["income_items"]) > 0
        assert len(slip["deduction_items"]) > 0
        assert slip["gross_salary_yuan"] > 0
        assert slip["net_pay_yuan"] > 0

        # Income items should have both fen and yuan
        for item in slip["income_items"]:
            assert "amount_fen" in item
            assert "amount_yuan" in item

    def test_store_labor_cost(self, payroll_svc):
        """门店人力成本分析"""
        payroll_svc.calculate_payroll(STORE_ID, "2026-03")

        cost = payroll_svc.get_store_labor_cost(
            STORE_ID, "2026-03", revenue_fen=200_000_000  # 200万营收
        )

        assert cost["total_labor_cost_fen"] > 0
        assert cost["employee_count"] == 10
        assert cost["per_employee_cost_fen"] > 0
        assert cost["labor_cost_rate_pct"] > 0
        assert cost["labor_cost_rate_pct"] < 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Tax Calculation Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTaxCalculation:
    """个税阶梯计算测试"""

    def test_tax_tier_1(self, payroll_svc):
        """第1级：0-36000 → 3%"""
        result = payroll_svc.calculate_tax(3_000_000)  # 30000 yuan = 3000000 fen
        assert result["rate"] == 0.03
        assert result["tax_yuan"] == 30000 * 0.03

    def test_tax_tier_2(self, payroll_svc):
        """第2级：36000-144000 → 10%"""
        result = payroll_svc.calculate_tax(10_000_000)  # 100000 yuan
        assert result["rate"] == 0.10
        expected = 100000 * 0.10 - 2520
        assert result["tax_yuan"] == expected

    def test_tax_tier_3(self, payroll_svc):
        """第3级：144000-300000 → 20%"""
        result = payroll_svc.calculate_tax(20_000_000)  # 200000 yuan
        assert result["rate"] == 0.20
        expected = 200000 * 0.20 - 16920
        assert result["tax_yuan"] == expected

    def test_tax_tier_4(self, payroll_svc):
        """第4级：300000-420000 → 25%"""
        result = payroll_svc.calculate_tax(35_000_000)  # 350000 yuan
        assert result["rate"] == 0.25
        expected = 350000 * 0.25 - 31920
        assert result["tax_yuan"] == expected

    def test_tax_tier_5(self, payroll_svc):
        """第5级：420000-660000 → 30%"""
        result = payroll_svc.calculate_tax(50_000_000)  # 500000 yuan
        assert result["rate"] == 0.30
        expected = 500000 * 0.30 - 52920
        assert result["tax_yuan"] == expected

    def test_tax_tier_6(self, payroll_svc):
        """第6级：660000-960000 → 35%"""
        result = payroll_svc.calculate_tax(80_000_000)  # 800000 yuan
        assert result["rate"] == 0.35
        expected = 800000 * 0.35 - 85920
        assert result["tax_yuan"] == expected

    def test_tax_tier_7(self, payroll_svc):
        """第7级：960000+ → 45%"""
        result = payroll_svc.calculate_tax(100_000_000)  # 1000000 yuan
        assert result["rate"] == 0.45
        expected = 1000000 * 0.45 - 181920
        assert result["tax_yuan"] == expected

    def test_tax_zero_income(self, payroll_svc):
        """零收入不纳税"""
        result = payroll_svc.calculate_tax(0)
        assert result["tax_yuan"] == 0
        assert result["rate"] == 0

    def test_tax_boundary_36000(self, payroll_svc):
        """边界值：恰好36000"""
        result = payroll_svc.calculate_tax(3_600_000)
        assert result["rate"] == 0.03
        assert result["tax_yuan"] == 36000 * 0.03  # 1080


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. Social Insurance Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSocialInsurance:
    """长沙五险一金测试"""

    def test_changsha_rates(self, payroll_svc):
        """长沙2026费率验证"""
        si = payroll_svc.calculate_social_insurance(800_000, "changsha", 0.08)

        # Verify rates
        assert si["pension"]["company_rate"] == 0.16
        assert si["pension"]["employee_rate"] == 0.08
        assert si["medical"]["company_rate"] == 0.08
        assert si["medical"]["employee_rate"] == 0.02
        assert si["unemployment"]["company_rate"] == 0.007
        assert si["unemployment"]["employee_rate"] == 0.003
        assert si["work_injury"]["company_rate"] == 0.005
        assert si["maternity"]["company_rate"] == 0.007
        assert si["housing_fund"]["rate"] == 0.08

    def test_pension_calculation(self, payroll_svc):
        """养老保险计算"""
        base = 800_000  # 8000 yuan
        si = payroll_svc.calculate_social_insurance(base, "changsha")

        assert si["pension"]["company_fen"] == int(base * 0.16)
        assert si["pension"]["employee_fen"] == int(base * 0.08)

    def test_base_floor_clamping(self, payroll_svc):
        """社保基数下限限制"""
        low_salary = 300_000  # 3000 yuan, below floor of 3747
        si = payroll_svc.calculate_social_insurance(low_salary, "changsha")

        # Should use floor (374700 fen) not actual salary
        assert si["si_base_fen"] == 374_700
        assert si["pension"]["employee_fen"] == int(374_700 * 0.08)

    def test_base_ceiling_clamping(self, payroll_svc):
        """社保基数上限限制"""
        high_salary = 3_000_000  # 30000 yuan, above ceiling
        si = payroll_svc.calculate_social_insurance(high_salary, "changsha")

        assert si["si_base_fen"] == 2_124_300  # ceiling
        assert si["pension"]["employee_fen"] == int(2_124_300 * 0.08)

    def test_housing_fund_rate_options(self, payroll_svc):
        """公积金比例可选5%-12%"""
        base = 800_000

        si_5 = payroll_svc.calculate_social_insurance(base, "changsha", 0.05)
        si_12 = payroll_svc.calculate_social_insurance(base, "changsha", 0.12)

        assert si_12["housing_fund"]["employee_fen"] > si_5["housing_fund"]["employee_fen"]
        assert si_5["housing_fund"]["rate"] == 0.05
        assert si_12["housing_fund"]["rate"] == 0.12

    def test_total_company_vs_employee(self, payroll_svc):
        """公司缴纳应高于个人缴纳"""
        si = payroll_svc.calculate_social_insurance(800_000, "changsha")
        assert si["total_company_fen"] > si["total_employee_fen"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. Waste Guard V2 Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWasteGuardV2:
    """损耗监控V2测试"""

    def _seed_waste_records(self, wg: WasteGuardV2) -> None:
        """填充测试损耗数据"""
        records = [
            (STORE_ID, "ING001", 2.5, "expired", "过期3天", "EMP001", "2026-03-01"),
            (STORE_ID, "ING001", 1.0, "spoiled", "冷库温度异常", "EMP003", "2026-03-03"),
            (STORE_ID, "ING002", 3.0, "overproduction", "备餐过量", "EMP004", "2026-03-05"),
            (STORE_ID, "ING004", 1.5, "expired", "虾到期", "EMP001", "2026-03-07"),
            (STORE_ID, "ING005", 2.0, "damage", "搬运摔裂鱼缸", "EMP007", "2026-03-10"),
            (STORE_ID, "ING003", 4.0, "overproduction", "客流下降", "EMP004", "2026-03-12"),
            (STORE_ID, "ING009", 5.0, "spoiled", "未及时冷藏", "EMP005", "2026-03-15"),
            (STORE_ID, "ING001", 1.5, "expired", "又过期了", "EMP001", "2026-03-18"),
            (STORE_ID, "ING002", 2.0, "overproduction", "周末备餐过多", "EMP004", "2026-03-20"),
            (STORE_ID, "ING008", 3.0, "other", "洒了一桶油", "EMP008", "2026-03-22"),
        ]
        for r in records:
            wg.record_waste(*r, record_date=r[6])

    def test_record_waste(self, waste_guard):
        """记录损耗"""
        result = waste_guard.record_waste(
            STORE_ID, "ING001", 2.5, "expired",
            "过期3天", "EMP001", record_date="2026-03-01",
        )
        assert result["ok"]
        assert result["waste_cost_yuan"] == 100.0  # 2.5kg * 40 yuan/kg

    def test_invalid_waste_type(self, waste_guard):
        """无效损耗类型"""
        result = waste_guard.record_waste(
            STORE_ID, "ING001", 1.0, "invalid_type",
            "test", "EMP001",
        )
        assert not result["ok"]

    def test_waste_dashboard_top5(self, waste_guard):
        """损耗看板 TOP5"""
        self._seed_waste_records(waste_guard)

        dashboard = waste_guard.get_waste_dashboard(
            STORE_ID, "2026-03-01", "2026-03-31",
            revenue_fen=200_000_000,
            prev_waste_fen=50_000,
        )

        assert dashboard["record_count"] == 10
        assert dashboard["total_waste_fen"] > 0
        assert len(dashboard["top5_by_cost"]) <= 5
        assert len(dashboard["top5_by_quantity"]) <= 5

        # TOP1 by cost should have highest cost
        if len(dashboard["top5_by_cost"]) >= 2:
            assert (
                dashboard["top5_by_cost"][0]["waste_cost_fen"]
                >= dashboard["top5_by_cost"][1]["waste_cost_fen"]
            )

    def test_waste_dashboard_by_type(self, waste_guard):
        """按类型分类"""
        self._seed_waste_records(waste_guard)

        dashboard = waste_guard.get_waste_dashboard(
            STORE_ID, "2026-03-01", "2026-03-31",
        )

        by_type = dashboard["by_type"]
        assert "expired" in by_type
        assert "overproduction" in by_type
        assert by_type["expired"]["count"] >= 3

    def test_root_cause_analysis(self, waste_guard):
        """根因分析"""
        self._seed_waste_records(waste_guard)

        analysis = waste_guard.analyze_root_cause(
            STORE_ID, "ING001", days=30,
        )

        assert analysis["total_records"] >= 3  # 3 records for ING001
        assert len(analysis["root_causes"]) > 0
        assert len(analysis["recommendations"]) > 0
        assert analysis["ingredient_name"] == "猪肉"

    def test_improvement_plan(self, waste_guard):
        """整改计划创建"""
        self._seed_waste_records(waste_guard)

        analysis = waste_guard.analyze_root_cause(STORE_ID, "ING001")
        plan = waste_guard.create_improvement_plan(
            STORE_ID, analysis, target_reduction_pct=30.0, duration_days=30,
        )

        assert plan["ok"]
        assert plan["target_reduction_pct"] == 30.0
        assert plan["action_count"] > 0
        assert plan["target_cost_yuan"] < plan["baseline_cost_yuan"]

    def test_track_improvement(self, waste_guard):
        """整改跟踪"""
        self._seed_waste_records(waste_guard)

        analysis = waste_guard.analyze_root_cause(STORE_ID, "ING001")
        plan = waste_guard.create_improvement_plan(STORE_ID, analysis)
        plan_id = plan["plan_id"]

        tracking = waste_guard.track_improvement(plan_id)

        assert tracking["plan_id"] == plan_id
        assert "baseline_cost_yuan" in tracking
        assert "progress_pct" in tracking
        assert tracking["action_items_total"] > 0

    def test_waste_prediction(self, waste_guard):
        """损耗预测"""
        self._seed_waste_records(waste_guard)

        prediction = waste_guard.predict_waste(STORE_ID, "ING001", days_ahead=7)

        assert prediction["has_data"]
        assert len(prediction["daily_predictions"]) == 7
        assert prediction["total_predicted_cost_fen"] > 0

        for dp in prediction["daily_predictions"]:
            assert "predicted_qty_kg" in dp
            assert "confidence" in dp

    def test_waste_prediction_no_data(self, waste_guard):
        """无历史数据时的预测"""
        prediction = waste_guard.predict_waste(STORE_ID, "ING001", days_ahead=7)

        assert not prediction["has_data"]
        assert "历史数据不足" in prediction["message"]

    def test_waste_cost_impact(self, waste_guard):
        """损耗成本影响"""
        self._seed_waste_records(waste_guard)

        impact = waste_guard.get_waste_cost_impact(
            STORE_ID, "2026-03",
            revenue_fen=200_000_000,
            cogs_fen=80_000_000,
        )

        assert impact["total_waste_fen"] > 0
        assert impact["waste_vs_revenue_pct"] > 0
        assert impact["waste_vs_cogs_pct"] > 0
        assert impact["potential_annual_savings_yuan"] > 0
        assert impact["status"] in ("ok", "warning", "critical")

    def test_waste_rate_summary_in_dashboard(self, waste_guard):
        """看板中的损耗率摘要"""
        self._seed_waste_records(waste_guard)

        dashboard = waste_guard.get_waste_dashboard(
            STORE_ID, "2026-03-01", "2026-03-31",
            revenue_fen=200_000_000,
            prev_waste_fen=50_000,
        )

        summary = dashboard["waste_rate_summary"]
        assert summary is not None
        assert "waste_rate_pct" in summary
        assert "waste_rate_status" in summary
        assert "vs_previous" in summary


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. Integration Scenarios
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestIntegration:
    """端到端集成场景"""

    def test_schedule_to_payroll_pipeline(self):
        """排班 → 考勤 → 薪资 完整流水线"""
        # 1. Generate schedule
        sched_svc = SmartScheduleService()
        start = date(2026, 3, 23)
        schedule = sched_svc.generate_schedule(STORE_ID, start)

        # 2. Extract scheduled shifts for attendance engine
        emp_shifts: dict = {}
        for date_str, day_sch in schedule["schedule"].items():
            for shift_name, emp_list in day_sch.items():
                for emp_id in emp_list:
                    if emp_id not in emp_shifts:
                        emp_shifts[emp_id] = {}
                    emp_shifts[emp_id][date_str] = shift_name

        # 3. Create attendance engine with schedule
        att_engine = AttendanceEngine(scheduled_shifts=emp_shifts)

        # 4. Simulate clock-in/out for EMP001 for the week
        for day_offset in range(7):
            d = start + timedelta(days=day_offset)
            d_str = d.isoformat()
            if d_str in emp_shifts.get("EMP001", {}):
                shift = emp_shifts["EMP001"][d_str]
                shift_time = SHIFT_TIMES.get(shift, {})
                if shift_time:
                    start_t = shift_time["start"]
                    end_t = shift_time["end"]
                    att_engine.clock_in(
                        "EMP001", STORE_ID,
                        clock_time=datetime.combine(d, start_t),
                    )
                    att_engine.clock_out(
                        "EMP001", STORE_ID,
                        clock_time=datetime.combine(d, end_t),
                    )

        # 5. Get monthly summary
        summary = att_engine.get_monthly_summary("EMP001", "2026-03")
        assert summary["late_count"] == 0

        # 6. Calculate payroll using attendance data
        payroll_svc = PayrollService()
        payroll = payroll_svc.calculate_employee_payroll(
            "EMP001", "2026-03",
            attendance_data={
                "attendance_days": summary["work_days"],
                "absence_days": summary["absent_count"],
                "late_count": summary["late_count"],
                "early_leave_count": summary["early_leave_count"],
            },
        )

        assert payroll["ok"]
        assert payroll["net_pay_fen"] > 0

    def test_employee_database_consistency(self):
        """员工数据库10人一致性"""
        assert len(EMPLOYEE_DATABASE) == 10
        assert len(EMPLOYEE_SALARY_CONFIG) == 10

        # Same IDs in both
        sched_ids = {e["employee_id"] for e in EMPLOYEE_DATABASE}
        pay_ids = {e["employee_id"] for e in EMPLOYEE_SALARY_CONFIG}
        assert sched_ids == pay_ids

        # All have required fields
        for emp in EMPLOYEE_DATABASE:
            assert "name" in emp
            assert "skills" in emp
            assert len(emp["skills"]) > 0

        for cfg in EMPLOYEE_SALARY_CONFIG:
            assert cfg["base_salary_fen"] > 0
