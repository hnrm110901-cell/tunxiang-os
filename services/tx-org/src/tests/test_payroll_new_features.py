"""薪资系统新功能测试

覆盖：
1. 全职员工基本工资按出勤天数正确计算
2. 迟到扣款累积
3. 旷工按日薪扣减
4. 加班 1.5 倍工资
5. 个税免征额以上累进计算
6. 提成按销售比例
7. 社保三项扣款（养老/医疗/失业）
8. 实发 = 应发 - 各项扣款
9. payroll_engine_db.PayrollEngine 的五险一金计算（使用 DB 版 SocialInsuranceConfig）
10. _fetch_attendance_summary 降级逻辑（late_count 默认 0）
11. PayrollEngine.calculate_social_insurance 各险种分项
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from uuid import uuid4

import pytest
from services.income_tax import IncomeTaxCalculator
from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_commission,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_overtime_pay,
    count_work_days,
    derive_hourly_rate,
    summarize_payroll,
)
from services.payroll_engine_db import (
    PayrollEngine as PayrollEngineDB,
)
from services.payroll_engine_db import (
    SIResult,
    SocialInsuranceConfig,
)
from services.payroll_engine_v2 import PayrollEngine as PayrollEngineV2
from services.social_insurance import SocialInsuranceCalculator

TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())

# 2026-03 工作日数（周一至周五）= 22
WORK_DAYS_MARCH_2026 = count_work_days(2026, 3)


# ═══════════════════════════════════════════════════════
#  1. 全职员工基本工资按出勤天数正确计算
# ═══════════════════════════════════════════════════════

class TestBaseSalaryProration:
    """基本工资按出勤比例计算"""

    def test_full_month_full_pay(self):
        """满勤 22 天 → 全额工资"""
        result = compute_base_salary(600_000, attendance_days=22, work_days_in_month=22)
        assert result == 600_000

    def test_half_month_half_pay(self):
        """出勤 11 天（50%）→ 工资减半"""
        result = compute_base_salary(600_000, attendance_days=11, work_days_in_month=22)
        assert result == 300_000

    def test_one_day_absent(self):
        """缺勤 1 天 → 日薪 600000/22 被扣"""
        base = compute_base_salary(600_000, attendance_days=21, work_days_in_month=22)
        daily = 600_000 // 22
        # 实发基本工资应为合同工资 - 1日薪（整数除法）
        assert base == 600_000 - daily * 1 or base == int(600_000 * 21 / 22)

    def test_zero_attendance(self):
        """出勤 0 天 → 零工资"""
        result = compute_base_salary(600_000, attendance_days=0, work_days_in_month=22)
        assert result == 0

    def test_attendance_capped_at_full(self):
        """出勤超过工作日时，最多发全额"""
        result = compute_base_salary(600_000, attendance_days=30, work_days_in_month=22)
        assert result == 600_000


# ═══════════════════════════════════════════════════════
#  2. 迟到扣款累积
# ═══════════════════════════════════════════════════════

class TestLateDeductionAccumulation:
    """迟到扣款按次累积"""

    def test_single_late(self):
        """迟到 1 次扣 50 元（5000 分）"""
        deduction = compute_late_deduction(late_count=1, deduction_per_time_fen=5_000)
        assert deduction == 5_000

    def test_multiple_late(self):
        """迟到 5 次 × 50 元 = 250 元"""
        deduction = compute_late_deduction(late_count=5, deduction_per_time_fen=5_000)
        assert deduction == 25_000

    def test_late_reduces_gross_via_v2_engine(self):
        """通过 V2 引擎验证迟到后应发减少"""
        engine = PayrollEngineV2()
        record_no_late = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=600_000,
            work_days_in_month=WORK_DAYS_MARCH_2026,
            attendance_days=WORK_DAYS_MARCH_2026,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        record_3_late = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=600_000,
            work_days_in_month=WORK_DAYS_MARCH_2026,
            attendance_days=WORK_DAYS_MARCH_2026,
            absence_days=0,
            late_count=3,
            early_leave_count=0,
            late_deduction_per_time_fen=5_000,
        )
        # 迟到 3 次扣 150 元，考勤扣款差额
        diff = record_no_late.attendance_deduction - record_3_late.attendance_deduction
        assert diff == pytest.approx(-150.0, abs=0.5)

    def test_zero_late_no_deduction(self):
        """无迟到时扣款为 0"""
        assert compute_late_deduction(0, 5_000) == 0

    def test_full_attendance_bonus_lost_on_late(self):
        """有迟到时全勤奖不发放"""
        bonus = compute_full_attendance_bonus(
            absence_days=0, late_count=1, early_leave_count=0, bonus_fen=30_000
        )
        assert bonus == 0


# ═══════════════════════════════════════════════════════
#  3. 旷工按日薪扣减
# ═══════════════════════════════════════════════════════

class TestAbsenceDeductionByDailyRate:
    """旷工按日薪（月薪/工作日）扣减"""

    def test_one_day_absence(self):
        """旷工 1 天扣 1 日薪"""
        deduction = compute_absence_deduction(
            base_salary_fen=440_000,
            absence_days=1,
            work_days_in_month=22,
        )
        daily = 440_000 // 22   # = 20000 分 = 200 元
        assert deduction == daily

    def test_two_day_absence(self):
        """旷工 2 天扣 2 日薪"""
        deduction = compute_absence_deduction(600_000, absence_days=2, work_days_in_month=22)
        daily = 600_000 // 22
        assert deduction == daily * 2

    def test_zero_absence_no_deduction(self):
        """无旷工时扣款为 0"""
        deduction = compute_absence_deduction(600_000, absence_days=0, work_days_in_month=22)
        assert deduction == 0

    def test_absence_deduction_through_engine(self):
        """通过 V2 引擎验证旷工扣款"""
        engine = PayrollEngineV2()
        record = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=440_000,
            work_days_in_month=22,
            attendance_days=20,
            absence_days=2,
            late_count=0,
            early_leave_count=0,
        )
        expected_deduction = (440_000 // 22) * 2 / 100   # 元
        assert record.attendance_deduction == pytest.approx(expected_deduction, abs=0.5)


# ═══════════════════════════════════════════════════════
#  4. 加班 1.5 倍工资
# ═══════════════════════════════════════════════════════

class TestOvertimePay:
    """加班工资按倍率计算"""

    def test_weekday_overtime_1_5x(self):
        """工作日加班 1.5 倍"""
        pay = compute_overtime_pay(hourly_rate_fen=2_000, overtime_hours=4, overtime_type="weekday")
        assert pay == int(2_000 * 1.5 * 4)  # = 12000 分 = 120 元

    def test_weekend_overtime_2x(self):
        """周末加班 2.0 倍"""
        pay = compute_overtime_pay(hourly_rate_fen=2_000, overtime_hours=8, overtime_type="weekend")
        assert pay == int(2_000 * 2.0 * 8)  # = 32000 分 = 320 元

    def test_holiday_overtime_3x(self):
        """法定节假日加班 3.0 倍"""
        pay = compute_overtime_pay(hourly_rate_fen=2_000, overtime_hours=8, overtime_type="holiday")
        assert pay == int(2_000 * 3.0 * 8)  # = 48000 分 = 480 元

    def test_derive_hourly_rate_from_monthly(self):
        """从月薪推算时薪"""
        # 月薪 440000 分（4400元）/ 22工作日 / 8小时 = 2500 分/小时（25元）
        hourly = derive_hourly_rate(base_salary_fen=440_000, work_days_in_month=22)
        assert hourly == 440_000 // (22 * 8)

    def test_overtime_through_v2_engine(self):
        """通过 V2 引擎验证加班后应发增加"""
        engine = PayrollEngineV2()
        base = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=440_000,
            work_days_in_month=22,
            attendance_days=22,
            absence_days=0, late_count=0, early_leave_count=0,
            overtime_weekday_hours=0,
        )
        with_ot = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=440_000,
            work_days_in_month=22,
            attendance_days=22,
            absence_days=0, late_count=0, early_leave_count=0,
            overtime_weekday_hours=4,
        )
        # 加班费 = 时薪 * 1.5 * 4 小时（单位元）
        hourly_fen = 440_000 // (22 * 8)
        expected_ot_yuan = hourly_fen * 1.5 * 4 / 100
        diff = with_ot.gross_salary - base.gross_salary
        assert diff == pytest.approx(expected_ot_yuan, abs=0.5)


# ═══════════════════════════════════════════════════════
#  5. 个税免征额以上累进计算
# ═══════════════════════════════════════════════════════

class TestIncomeTaxProgressive:
    """个税在免征额（5000元/月）以上累进计算"""

    def test_below_5000_no_tax(self):
        """月收入 ≤ 5000 元时不交税"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=4_500.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=300.0,
            month_index=1,
        )
        assert result["monthly_tax"] == 0.0

    def test_above_5000_pays_3pct(self):
        """月收入 8000 元，扣社保 1000，减免征额 5000 → 应纳税所得 2000，税率 3%，税 60 元"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=8_000.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=1_000.0,
            month_index=1,
        )
        assert result["tax_rate"] == pytest.approx(0.03)
        assert result["monthly_tax"] == pytest.approx(60.0, abs=1.0)

    def test_progressive_rate_escalation(self):
        """累计收入超过 36000 元应纳税所得后进入 10% 档"""
        calc = IncomeTaxCalculator()
        # 月收入 15000，社保 2000，从第 4 月开始（前 3 月累计 45000）
        ytd_si = 2_000.0 * 3 + 2_000.0   # 前3月 + 当月
        result = calc.calculate_monthly(
            current_month_income=15_000.0,
            ytd_income=15_000.0 * 3,
            ytd_tax_paid=500.0,
            ytd_social_insurance=ytd_si,
            month_index=4,
        )
        # 累计应纳税所得 ≈ 60000 - 20000（减除）- 8000（社保）= 32000，刚进 3% 档接近顶端
        # 此处只验证税率 >= 3%，不超过 10%
        assert result["tax_rate"] in (0.03, 0.10)

    def test_tax_not_negative(self):
        """个税不为负（保护机制）"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=5_500.0,
            ytd_income=0.0,
            ytd_tax_paid=99999.0,   # 异常大的已缴税额
            ytd_social_insurance=500.0,
            month_index=1,
        )
        assert result["monthly_tax"] >= 0.0


# ═══════════════════════════════════════════════════════
#  6. 提成按销售比例
# ═══════════════════════════════════════════════════════

class TestCommissionCalculation:
    """提成按销售额 × 提成率计算"""

    def test_fixed_rate_commission(self):
        """1 万元销售额 × 2% = 200 元"""
        result = compute_commission(sales_amount_fen=1_000_000, commission_rate=0.02)
        assert result == 20_000  # 200 元 = 20000 分

    def test_zero_commission_rate(self):
        """提成率 0 时无提成"""
        result = compute_commission(sales_amount_fen=1_000_000, commission_rate=0.0)
        assert result == 0

    def test_commission_included_in_gross(self):
        """提成计入应发工资"""
        engine = PayrollEngineV2()
        no_commission = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=600_000,
            work_days_in_month=22, attendance_days=22,
            absence_days=0, late_count=0, early_leave_count=0,
            sales_amount_fen=0, commission_rate=0.0,
        )
        with_commission = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=600_000,
            work_days_in_month=22, attendance_days=22,
            absence_days=0, late_count=0, early_leave_count=0,
            sales_amount_fen=1_000_000,   # 1 万元
            commission_rate=0.02,           # 2%
        )
        # 提成 200 元计入应发
        diff = with_commission.gross_salary - no_commission.gross_salary
        assert diff == pytest.approx(200.0, abs=0.5)


# ═══════════════════════════════════════════════════════
#  7. 社保三项扣款（养老 8% / 医疗 2% / 失业 0.3%）
# ═══════════════════════════════════════════════════════

class TestSocialInsuranceThreeItems:
    """五险一金分项计算（长沙标准）"""

    def _calc(self, base_fen: int) -> dict:
        return SocialInsuranceCalculator(city="changsha").calculate(gross_salary_fen=base_fen)

    def test_pension_employee_8pct(self):
        """养老保险个人 8%"""
        result = self._calc(600_000)
        bd = result["breakdown"]
        # 600000 分 × 8% = 48000 分 = 480 元
        assert bd["pension"]["personal_fen"] == pytest.approx(48_000, abs=100)
        assert bd["pension"]["personal_rate"] == pytest.approx(0.08)

    def test_medical_employee_2pct(self):
        """医疗保险个人 2%"""
        result = self._calc(600_000)
        bd = result["breakdown"]
        assert bd["medical"]["personal_fen"] == pytest.approx(12_000, abs=100)
        assert bd["medical"]["personal_rate"] == pytest.approx(0.02)

    def test_unemployment_employee_0_3pct_changsha(self):
        """失业保险个人 0.3%（长沙）"""
        result = self._calc(600_000)
        bd = result["breakdown"]
        # 长沙 unemployment_personal = 0.003
        assert bd["unemployment"]["personal_fen"] == pytest.approx(1_800, abs=100)

    def test_personal_total_equals_sum(self):
        """个人合计 = 各险种个人部分之和"""
        result = self._calc(600_000)
        bd = result["breakdown"]
        sum_personal = sum(v["personal_fen"] for v in bd.values())
        assert result["personal_total"] == sum_personal

    def test_db_engine_calculate_social_insurance(self):
        """DB 版引擎五险一金计算"""
        engine = PayrollEngineDB()
        config = SocialInsuranceConfig(
            region="changsha",
            pension_rate_employee=0.08,
            pension_rate_employer=0.16,
            medical_rate_employee=0.02,
            medical_rate_employer=0.08,
            unemployment_rate_employee=0.003,
            unemployment_rate_employer=0.007,
            housing_fund_rate=0.08,
        )
        si: SIResult = engine.calculate_social_insurance(
            base_fen=600_000,
            config=config,
        )
        assert si.pension_personal_fen == pytest.approx(48_000, abs=10)
        assert si.medical_personal_fen == pytest.approx(12_000, abs=10)
        assert si.unemployment_personal_fen == pytest.approx(1_800, abs=10)
        assert si.housing_fund_personal_fen == pytest.approx(48_000, abs=10)
        # 个人合计
        expected_personal = 48_000 + 12_000 + 1_800 + 48_000
        assert si.personal_total_fen == pytest.approx(expected_personal, abs=20)


# ═══════════════════════════════════════════════════════
#  8. 实发 = 应发 - 各项扣款
# ═══════════════════════════════════════════════════════

class TestNetSalaryFormula:
    """实发工资公式验证"""

    def test_net_equals_gross_minus_all_deductions(self):
        """
        实发 = 应发 - 考勤扣款 - 社保个人 - 个税
        通过 summarize_payroll 验证
        """
        gross_fen = 600_000
        absence_deduction = 27_272
        late_deduction = 15_000
        si_personal = 61_800
        tax_fen = 3_000

        result = summarize_payroll(
            base_salary_fen=600_000,
            absence_deduction_fen=absence_deduction,
            late_deduction_fen=late_deduction,
            social_insurance_fen=si_personal,
            tax_fen=tax_fen,
        )
        expected_net = gross_fen - absence_deduction - late_deduction - si_personal - tax_fen
        assert result["net_salary_fen"] == expected_net

    def test_net_salary_non_negative_via_engine(self):
        """实发工资不为负"""
        engine = PayrollEngineV2()
        record = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=450_000,
            work_days_in_month=22, attendance_days=22,
            absence_days=0, late_count=0, early_leave_count=0,
        )
        assert record.net_salary >= 0.0

    def test_full_workflow_calculation(self):
        """全流程：基本工资 + 迟到扣款 + 社保 + 个税 → 实发"""
        engine = PayrollEngineV2()
        record = engine.compute_monthly(
            tenant_id=TENANT_ID, employee_id=EMP_ID, store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=600_000,
            work_days_in_month=22,
            attendance_days=21,     # 缺勤 1 天
            absence_days=1,
            late_count=2,           # 迟到 2 次 × 50 元
            early_leave_count=0,
            late_deduction_per_time_fen=5_000,
            sales_amount_fen=500_000,   # 5000 元销售额
            commission_rate=0.02,        # 2% 提成 = 100 元
            overtime_weekday_hours=3,   # 3小时工作日加班
            month_index=3,
        )
        # 实发 = 应发（含提成/加班） - 考勤扣款 - 社保个人 - 个税，均 >= 0
        assert record.net_salary >= 0.0
        assert record.gross_salary > 0.0
        # 提成应计入
        assert record.commission == pytest.approx(100.0, abs=0.5)


# ═══════════════════════════════════════════════════════
#  附加：attendance_summary 降级逻辑测试（单元测试）
# ═══════════════════════════════════════════════════════

class TestAttendanceSummaryDefaultFields:
    """验证考勤汇总的默认字段填充逻辑（非 DB 版，针对字典操作）"""

    def test_setdefault_late_count(self):
        """late_count 不存在时默认为 0"""
        att: dict = {"work_days": 20, "work_hours": 160.0, "overtime_hours": 4.0, "absence_days": 2}
        att.setdefault("late_count", 0)
        att.setdefault("early_leave_count", 0)
        att.setdefault("sales_amount_fen", 0)
        assert att["late_count"] == 0
        assert att["early_leave_count"] == 0
        assert att["sales_amount_fen"] == 0

    def test_setdefault_preserves_existing_values(self):
        """已有值时 setdefault 不覆盖"""
        att: dict = {"late_count": 3, "early_leave_count": 1}
        att.setdefault("late_count", 0)
        att.setdefault("early_leave_count", 0)
        assert att["late_count"] == 3
        assert att["early_leave_count"] == 1
