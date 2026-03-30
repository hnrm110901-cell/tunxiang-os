"""薪资计算引擎测试

覆盖：
1. 基本工资 + 考勤扣款计算（缺勤按天扣）
2. 提成计算（销售额 × 提成率）
3. 五险一金计算（2026年费率）
4. 个税计算（累计预扣法，2024年税率表）
5. 净工资 = 应发工资 - 五险一金个人部分 - 个税
6. 多月累计个税（前几月已缴税影响当月税率）
7. 全勤奖：当月出勤率100%时附加奖金
8. tenant_id 隔离
"""

from __future__ import annotations

import sys
import os

# 确保 src 目录在导入路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from uuid import uuid4

from services.social_insurance import SocialInsuranceCalculator, CITY_RATES
from services.income_tax import IncomeTaxCalculator, TAX_BRACKETS, BASIC_DEDUCTION
from services.payroll_engine_v2 import PayrollEngine
from models.payroll_record import PayrollRecord, PayrollRecordStatus


# ── 测试数据常量 ────────────────────────────────────────────────────────────

TENANT_A = str(uuid4())
TENANT_B = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())
EMP_ID_2 = str(uuid4())

BASE_SALARY_FEN = 600_000       # 6000 元/月
WORK_DAYS = 22                   # 22 个工作日/月（2026-03）


# ══════════════════════════════════════════════════════════════════════════════
#  1. 基本工资 + 考勤扣款
# ══════════════════════════════════════════════════════════════════════════════

class TestBaseSalaryAndAttendance:
    """基本工资 + 考勤扣款（缺勤按天扣）"""

    def test_full_attendance_no_deduction(self):
        """满勤时无考勤扣款，应发=合同工资"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        assert record.attendance_deduction == 0.0
        # base_salary 字段存合同工资
        assert record.base_salary == BASE_SALARY_FEN / 100

    def test_absence_deduction_by_day(self):
        """缺勤 2 天按日薪扣款"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS - 2,
            absence_days=2,
            late_count=0,
            early_leave_count=0,
        )
        # 日薪 = 600000 / 22 = 27272 分 ≈ 272.72 元
        # 2天扣款 = 27272 * 2 = 54544 分 ≈ 545.44 元
        daily_rate_fen = BASE_SALARY_FEN // WORK_DAYS
        expected_deduction = daily_rate_fen * 2
        assert record.attendance_deduction == pytest.approx(expected_deduction / 100, rel=0.01)

    def test_late_deduction(self):
        """迟到 3 次，每次扣 50 元"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=3,
            early_leave_count=0,
            late_deduction_per_time_fen=5_000,
        )
        # 迟到扣款 = 3 * 50 = 150 元
        assert record.attendance_deduction == pytest.approx(150.0, rel=0.01)

    def test_net_salary_equals_gross_minus_deductions(self):
        """净工资 = 应发 - 五险一金个人 - 个税（基本公式验证）"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS - 1,
            absence_days=1,
            late_count=0,
            early_leave_count=0,
            month_index=3,
        )
        # 实发 ≈ 应发 - 考勤扣款 - 社保个人 - 个税
        gross_after_attendance = record.gross_salary - record.attendance_deduction
        expected_net = gross_after_attendance - (record.social_insurance_personal or 0) - record.income_tax
        assert record.net_salary == pytest.approx(expected_net, abs=0.5)


# ══════════════════════════════════════════════════════════════════════════════
#  2. 提成计算
# ══════════════════════════════════════════════════════════════════════════════

class TestCommission:
    """提成计算（销售额 × 提成率）"""

    def test_basic_commission(self):
        """固定提成率：销售额 10 万 × 0.5% = 500 元"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            sales_amount_fen=10_000_000,   # 10 万元
            commission_rate=0.005,          # 0.5%
        )
        assert record.commission == pytest.approx(500.0, abs=0.5)

    def test_zero_commission_rate(self):
        """提成率为 0 时无提成"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            sales_amount_fen=10_000_000,
            commission_rate=0.0,
        )
        assert record.commission == 0.0

    def test_commission_included_in_gross(self):
        """提成计入应发工资"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            sales_amount_fen=5_000_000,
            commission_rate=0.01,
        )
        # 应发应包含提成 = 5万 × 1% = 500 元
        assert record.gross_salary >= record.base_salary + 500.0 - 0.5


# ══════════════════════════════════════════════════════════════════════════════
#  3. 五险一金计算
# ══════════════════════════════════════════════════════════════════════════════

class TestSocialInsurance:
    """五险一金计算（2026年标准）"""

    def test_pension_rate(self):
        """养老保险：个人 8%，公司 16%"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000)
        breakdown = result["breakdown"]
        # 社保基数下限 374700 分，600000 > 374700 用 600000
        # 养老个人 = 600000 * 8% = 48000 分 = 480 元
        assert breakdown["pension"]["personal_fen"] == pytest.approx(48_000, abs=100)
        assert breakdown["pension"]["company_fen"] == pytest.approx(96_000, abs=100)

    def test_medical_rate(self):
        """医疗保险：个人 2%，公司 8%"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000)
        breakdown = result["breakdown"]
        assert breakdown["medical"]["personal_fen"] == pytest.approx(12_000, abs=100)
        assert breakdown["medical"]["company_fen"] == pytest.approx(48_000, abs=100)

    def test_unemployment_rate(self):
        """失业保险：个人 0.3%（长沙），公司 0.7%"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000)
        breakdown = result["breakdown"]
        # 长沙失业保险个人 0.3%
        assert breakdown["unemployment"]["personal_fen"] == pytest.approx(1_800, abs=100)

    def test_housing_fund_default(self):
        """住房公积金默认 8%，个人=公司"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000)
        breakdown = result["breakdown"]
        assert breakdown["housing_fund"]["personal_fen"] == breakdown["housing_fund"]["company_fen"]

    def test_housing_fund_rate_override(self):
        """住房公积金个人比例可覆盖（如 5%）"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000, housing_fund_rate_override=0.05)
        breakdown = result["breakdown"]
        assert breakdown["housing_fund"]["personal_rate"] == pytest.approx(0.05, abs=0.001)

    def test_si_base_floor_clamp(self):
        """基数低于下限时按下限计算"""
        calc = SocialInsuranceCalculator(city="changsha")
        # 长沙下限 374700 分
        result = calc.calculate(gross_salary_fen=200_000)  # 低于下限
        assert result["si_base_fen"] == 374_700

    def test_personal_total_structure(self):
        """个人合计 = 各险种个人之和"""
        calc = SocialInsuranceCalculator(city="changsha")
        result = calc.calculate(gross_salary_fen=600_000)
        breakdown = result["breakdown"]
        expected_personal = sum(
            v["personal_fen"] for v in breakdown.values()
        )
        assert result["personal_total"] == expected_personal

    def test_city_config_override(self):
        """城市配置可覆盖默认费率"""
        calc = SocialInsuranceCalculator(city="changsha")
        # 覆盖养老个人比例为 6%
        custom_config = {"pension_personal": 0.06}
        result = calc.calculate(gross_salary_fen=600_000, city_config=custom_config)
        # 600000 * 6% = 36000
        assert result["breakdown"]["pension"]["personal_fen"] == pytest.approx(36_000, abs=100)


# ══════════════════════════════════════════════════════════════════════════════
#  4. 个税计算（累计预扣法）
# ══════════════════════════════════════════════════════════════════════════════

class TestIncomeTax:
    """个税计算（2024年累计预扣法）"""

    def test_below_threshold_no_tax(self):
        """月收入低于 5000 元免税"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=4_000.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=500.0,
            month_index=1,
        )
        assert result["monthly_tax"] == 0.0

    def test_first_bracket_3pct(self):
        """年度累计应纳税所得额 ≤ 3.6 万，税率 3%"""
        calc = IncomeTaxCalculator()
        # 月收入 8000，社保 1000，月减除 5000
        # 应纳税所得 = 8000 - 1000 - 5000 = 2000
        # 税额 = 2000 * 3% = 60
        result = calc.calculate_monthly(
            current_month_income=8_000.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=1_000.0,
            month_index=1,
        )
        assert result["monthly_tax"] == pytest.approx(60.0, abs=1.0)

    def test_second_bracket_10pct(self):
        """年度累计超过 3.6 万，进入 10% 档"""
        calc = IncomeTaxCalculator()
        # 月收入 20000，社保 2000，月减除 5000
        # 6个月后累计：应纳税所得 = 20000*6 - 2000*6 - 5000*6 = 78000
        # 年税 = 78000 * 10% - 2520 = 5280
        # 假设前 5 月已缴 3600 * 3% = 108（第一档），精确计算
        result = calc.calculate_monthly(
            current_month_income=20_000.0,
            ytd_income=20_000.0 * 5,
            ytd_tax_paid=0.0,  # 假设已通过其他方式预缴，此处测试税率档位
            ytd_social_insurance=2_000.0 * 6,
            month_index=6,
        )
        assert result["tax_rate"] == pytest.approx(0.10)

    def test_zero_income_zero_tax(self):
        """应税收入为 0 时税额为 0"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=0.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=0.0,
            month_index=1,
        )
        assert result["monthly_tax"] == 0.0

    def test_annual_tax_calculation(self):
        """年度个税计算（汇算用）"""
        calc = IncomeTaxCalculator()
        # 年度应纳税所得额 5 万，税率 10%，速算扣除 2520
        result = calc.calculate_from_annual(50_000.0)
        assert result["tax_rate"] == pytest.approx(0.10)
        assert result["annual_tax"] == pytest.approx(2_480.0, abs=1.0)


# ══════════════════════════════════════════════════════════════════════════════
#  5. 净工资公式验证
# ══════════════════════════════════════════════════════════════════════════════

class TestNetSalaryFormula:
    """净工资 = 应发工资 - 五险一金个人部分 - 个税"""

    def test_net_salary_formula(self):
        """验证净工资计算公式正确性"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=800_000,  # 8000 元
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            month_index=3,
        )
        # 净工资 = 应发 - 考勤扣款 - 社保个人 - 个税
        gross_after = record.gross_salary - record.attendance_deduction
        calculated_net = gross_after - (record.social_insurance_personal or 0) - record.income_tax
        assert record.net_salary == pytest.approx(calculated_net, abs=0.1)

    def test_net_salary_positive(self):
        """净工资不为负"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=450_000,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        assert record.net_salary >= 0


# ══════════════════════════════════════════════════════════════════════════════
#  6. 多月累计个税
# ══════════════════════════════════════════════════════════════════════════════

class TestCumulativeTax:
    """多月累计个税：前几月已缴税影响当月税率"""

    def test_cumulative_increases_rate(self):
        """年中累计收入增加后，当月税率可能升档"""
        calc = IncomeTaxCalculator()

        # 第 1 月：月收入 1 万，社保 1500，无前期累计
        result_m1 = calc.calculate_monthly(
            current_month_income=10_000.0,
            ytd_income=0.0,
            ytd_tax_paid=0.0,
            ytd_social_insurance=1_500.0,
            month_index=1,
        )
        # 累计应纳税所得额 = 10000 - 5000 - 1500 = 3500，在 36000 以内，税率 3%
        assert result_m1["tax_rate"] == pytest.approx(0.03)

        # 第 5 月：已累计前4月收入 4 万，社保 6000，前期已缴税
        ytd_income_m4 = 10_000.0 * 4
        ytd_si_m4 = 1_500.0 * 4
        ytd_tax_m4 = result_m1["monthly_tax"] * 4  # 近似

        result_m5 = calc.calculate_monthly(
            current_month_income=10_000.0,
            ytd_income=ytd_income_m4,
            ytd_tax_paid=ytd_tax_m4,
            ytd_social_insurance=ytd_si_m4 + 1_500.0,  # 含当月
            month_index=5,
        )
        # 5月累计应纳税所得额 = 50000 - 25000 - 7500 = 17500，仍在第一档
        # 但税率和已缴税影响当月税额
        assert result_m5["monthly_tax"] >= 0

    def test_previous_tax_reduces_current_month(self):
        """前期已缴税款越多，当月应缴税越少"""
        calc = IncomeTaxCalculator()

        result_with_low_ytd = calc.calculate_monthly(
            current_month_income=15_000.0,
            ytd_income=50_000.0,
            ytd_tax_paid=100.0,  # 少量已缴
            ytd_social_insurance=10_000.0,
            month_index=5,
        )
        result_with_high_ytd = calc.calculate_monthly(
            current_month_income=15_000.0,
            ytd_income=50_000.0,
            ytd_tax_paid=1_000.0,  # 大量已缴
            ytd_social_insurance=10_000.0,
            month_index=5,
        )
        # 已缴税更多时，当月应缴税更少
        assert result_with_high_ytd["monthly_tax"] <= result_with_low_ytd["monthly_tax"]

    def test_monthly_tax_never_negative(self):
        """当月税额不为负（已缴税过多时返回 0）"""
        calc = IncomeTaxCalculator()
        result = calc.calculate_monthly(
            current_month_income=5_000.0,
            ytd_income=10_000.0,
            ytd_tax_paid=9_999.0,  # 异常大的已缴税额
            ytd_social_insurance=2_000.0,
            month_index=3,
        )
        assert result["monthly_tax"] >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  7. 全勤奖
# ══════════════════════════════════════════════════════════════════════════════

class TestFullAttendanceBonus:
    """全勤奖：当月出勤率100%时附加奖金"""

    def test_full_attendance_gets_bonus(self):
        """无缺勤无迟到，发放全勤奖"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            full_attendance_bonus_fen=30_000,  # 300 元
        )
        # allowances 字段包含全勤奖
        details = record.details or {}
        income = details.get("income", {})
        full_attend_fen = income.get("full_attendance_bonus_fen", 0)
        assert full_attend_fen == 30_000

    def test_one_late_no_bonus(self):
        """有迟到，不发全勤奖"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=1,
            early_leave_count=0,
            full_attendance_bonus_fen=30_000,
        )
        details = record.details or {}
        income = details.get("income", {})
        full_attend_fen = income.get("full_attendance_bonus_fen", 0)
        assert full_attend_fen == 0

    def test_one_absence_no_bonus(self):
        """有缺勤，不发全勤奖"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS - 1,
            absence_days=1,
            late_count=0,
            early_leave_count=0,
            full_attendance_bonus_fen=30_000,
        )
        details = record.details or {}
        income = details.get("income", {})
        full_attend_fen = income.get("full_attendance_bonus_fen", 0)
        assert full_attend_fen == 0

    def test_bonus_increases_gross(self):
        """全勤奖计入应发工资"""
        engine = PayrollEngine()
        bonus_fen = 30_000

        record_with_bonus = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            full_attendance_bonus_fen=bonus_fen,
        )
        record_no_bonus = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
            full_attendance_bonus_fen=0,
        )
        # 全勤奖使应发增加 300 元
        assert record_with_bonus.gross_salary - record_no_bonus.gross_salary == pytest.approx(300.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
#  8. tenant_id 隔离
# ══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    """tenant_id 隔离：不同租户的工资记录互不干扰"""

    def test_different_tenants_get_different_records(self):
        """不同 tenant_id 计算的记录各自隔离"""
        engine = PayrollEngine()
        params = dict(
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )

        record_a = engine.compute_monthly(tenant_id=TENANT_A, **params)
        record_b = engine.compute_monthly(tenant_id=TENANT_B, **params)

        assert record_a.tenant_id != record_b.tenant_id
        assert str(record_a.tenant_id) == TENANT_A
        assert str(record_b.tenant_id) == TENANT_B
        # 计算结果相同（同样参数）
        assert record_a.gross_salary == record_b.gross_salary
        assert record_a.net_salary == record_b.net_salary

    def test_tenant_id_in_record(self):
        """工资记录中包含正确的 tenant_id"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        assert str(record.tenant_id) == TENANT_A

    def test_batch_compute_tenant_isolation(self):
        """批量计算时 tenant_id 正确传递到每条记录"""
        engine = PayrollEngine()
        employees = [
            {"employee_id": str(uuid4()), "base_salary_fen": 500_000,
             "work_days_in_month": WORK_DAYS, "attendance_days": WORK_DAYS,
             "absence_days": 0, "late_count": 0, "early_leave_count": 0},
            {"employee_id": str(uuid4()), "base_salary_fen": 600_000,
             "work_days_in_month": WORK_DAYS, "attendance_days": WORK_DAYS,
             "absence_days": 0, "late_count": 0, "early_leave_count": 0},
        ]
        summary = engine.batch_compute(
            tenant_id=TENANT_A,
            store_id=STORE_ID,
            payroll_month="2026-03",
            employees=employees,
        )
        assert summary.tenant_id == TENANT_A
        for record in summary.records:
            assert str(record.tenant_id) == TENANT_A


# ══════════════════════════════════════════════════════════════════════════════
#  附加：工资单状态流转
# ══════════════════════════════════════════════════════════════════════════════

class TestPayrollRecordStatus:
    """工资单状态：draft → confirmed → paid"""

    def test_initial_status_draft(self):
        """初始状态为草稿"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        assert record.status == PayrollRecordStatus.DRAFT

    def test_confirm_transition(self):
        """确认操作：draft → confirmed"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        record.confirm()
        assert record.status == PayrollRecordStatus.CONFIRMED
        assert record.confirmed_at is not None

    def test_pay_transition(self):
        """发放操作：confirmed → paid"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        record.confirm()
        record.mark_paid()
        assert record.status == PayrollRecordStatus.PAID
        assert record.paid_at is not None

    def test_cannot_confirm_twice(self):
        """不能重复确认"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        record.confirm()
        with pytest.raises(ValueError, match="草稿"):
            record.confirm()

    def test_details_json_has_audit_fields(self):
        """details JSON 包含完整审计字段"""
        engine = PayrollEngine()
        record = engine.compute_monthly(
            tenant_id=TENANT_A,
            employee_id=EMP_ID,
            store_id=STORE_ID,
            payroll_month="2026-03",
            base_salary_fen=BASE_SALARY_FEN,
            work_days_in_month=WORK_DAYS,
            attendance_days=WORK_DAYS,
            absence_days=0,
            late_count=0,
            early_leave_count=0,
        )
        assert record.details is not None
        assert "income" in record.details
        assert "deductions" in record.details
        assert "social_insurance" in record.details
        assert "income_tax" in record.details
        assert "summary" in record.details
        assert "computed_at" in record.details
