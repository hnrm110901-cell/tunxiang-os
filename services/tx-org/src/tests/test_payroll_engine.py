"""
薪资计算引擎测试 -- payroll_engine.py 纯函数测试
"""

import pytest
from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_commission,
    compute_early_leave_deduction,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_overtime_pay,
    compute_performance_bonus,
    compute_seniority_subsidy,
    compute_tax_yuan,
    compute_tiered_commission,
    count_work_days,
    safe_eval_expression,
    summarize_payroll,
    validate_formula,
)


class TestComputeBaseSalary:
    """基本工资计算"""

    def test_full_attendance(self):
        """满勤时应发全额基本工资"""
        result = compute_base_salary(
            base_salary_fen=500_000,  # 5000 元
            attendance_days=22,
            work_days_in_month=22,
        )
        assert result == 500_000

    def test_partial_attendance(self):
        """部分出勤按比例计算"""
        result = compute_base_salary(
            base_salary_fen=500_000,
            attendance_days=11,
            work_days_in_month=22,
        )
        assert result == 250_000  # 50%

    def test_zero_work_days(self):
        """工作日为0时返回0"""
        result = compute_base_salary(
            base_salary_fen=500_000,
            attendance_days=0,
            work_days_in_month=0,
        )
        assert result == 0

    def test_over_attendance_capped(self):
        """出勤天数超过工作日时，比例上限为1.0"""
        result = compute_base_salary(
            base_salary_fen=500_000,
            attendance_days=25,
            work_days_in_month=22,
        )
        assert result == 500_000


class TestComputeOvertimePay:
    """加班费计算"""

    def test_weekday_overtime(self):
        """工作日加班 1.5 倍"""
        result = compute_overtime_pay(
            hourly_rate_fen=2_000,  # 20 元/小时
            overtime_hours=4,
            overtime_type="weekday",
        )
        assert result == 12_000  # 20 * 1.5 * 4 = 120 元

    def test_weekend_overtime(self):
        """周末加班 2.0 倍"""
        result = compute_overtime_pay(
            hourly_rate_fen=2_000,
            overtime_hours=8,
            overtime_type="weekend",
        )
        assert result == 32_000  # 20 * 2.0 * 8 = 320 元

    def test_holiday_overtime(self):
        """法定节假日加班 3.0 倍"""
        result = compute_overtime_pay(
            hourly_rate_fen=2_000,
            overtime_hours=8,
            overtime_type="holiday",
        )
        assert result == 48_000  # 20 * 3.0 * 8 = 480 元


class TestComputeCommission:
    """提成计算"""

    def test_fixed_rate(self):
        """固定比例提成"""
        result = compute_commission(
            sales_amount_fen=1_000_000,  # 1 万元
            commission_rate=0.05,
        )
        assert result == 50_000  # 500 元

    def test_tiered_commission(self):
        """阶梯提成"""
        tiers = [
            (500_000, 0.03),       # 0-5000 元: 3%
            (1_000_000, 0.05),     # 5000-10000 元: 5%
            (float("inf"), 0.08),  # 10000+ 元: 8%
        ]
        # 销售额 8000 元 = 800000 分
        result = compute_tiered_commission(800_000, tiers)
        # 前 500000 分 * 3% = 15000
        # 后 300000 分 * 5% = 15000
        # 合计 30000 分 = 300 元
        assert result == 30_000


class TestAttendanceDeductions:
    """考勤扣款"""

    def test_absence_deduction(self):
        """缺勤扣款"""
        result = compute_absence_deduction(
            base_salary_fen=440_000,  # 4400 元，22 个工作日，日薪 200 元
            absence_days=2,
            work_days_in_month=22,
        )
        # 日薪 = 440000 / 22 = 20000 分
        # 扣款 = 20000 * 2 = 40000 分
        assert result == 40_000

    def test_late_deduction(self):
        """迟到扣款"""
        result = compute_late_deduction(
            late_count=3,
            deduction_per_time_fen=5_000,  # 每次 50 元
        )
        assert result == 15_000

    def test_early_leave_deduction(self):
        """早退扣款"""
        result = compute_early_leave_deduction(
            early_leave_count=1,
            deduction_per_time_fen=5_000,
        )
        assert result == 5_000


class TestPerformanceBonus:
    """绩效奖金"""

    def test_positive_coefficient(self):
        """绩效系数 > 1 时有奖金"""
        result = compute_performance_bonus(
            base_salary_fen=500_000,
            performance_coefficient=1.2,
        )
        assert abs(result - 100_000) <= 1  # 5000 * 0.2 = 1000 元

    def test_coefficient_one(self):
        """绩效系数 = 1 时无奖金"""
        result = compute_performance_bonus(
            base_salary_fen=500_000,
            performance_coefficient=1.0,
        )
        assert result == 0

    def test_coefficient_below_one(self):
        """绩效系数 < 1 时无奖金"""
        result = compute_performance_bonus(
            base_salary_fen=500_000,
            performance_coefficient=0.8,
        )
        assert result == 0


class TestSenioritySubsidy:
    """工龄补贴"""

    def test_short_seniority(self):
        """工龄不足 13 月，无补贴"""
        assert compute_seniority_subsidy(12) == 0

    def test_mid_seniority(self):
        """工龄 24-35 月，100 元/月"""
        assert compute_seniority_subsidy(30) == 10_000

    def test_long_seniority(self):
        """工龄 >= 48 月，200 元/月"""
        assert compute_seniority_subsidy(60) == 20_000


class TestFullAttendanceBonus:
    """全勤奖"""

    def test_qualify(self):
        """全勤时发放"""
        result = compute_full_attendance_bonus(
            absence_days=0, late_count=0, early_leave_count=0, bonus_fen=30_000,
        )
        assert result == 30_000

    def test_disqualify_late(self):
        """有迟到不发放"""
        result = compute_full_attendance_bonus(
            absence_days=0, late_count=1, early_leave_count=0, bonus_fen=30_000,
        )
        assert result == 0


class TestTax:
    """个税计算"""

    def test_zero_income(self):
        """收入为0时税额为0"""
        tax, rate, qd = compute_tax_yuan(0)
        assert tax == 0.0
        assert rate == 0.0

    def test_first_bracket(self):
        """第一档税率 3%"""
        tax, rate, qd = compute_tax_yuan(10_000)
        assert rate == 0.03
        assert tax == pytest.approx(300.0)

    def test_second_bracket(self):
        """第二档税率 10%"""
        tax, rate, qd = compute_tax_yuan(50_000)
        assert rate == 0.10
        # 50000 * 10% - 2520 = 2480
        assert tax == pytest.approx(2_480.0)


class TestCountWorkDays:
    """工作日计算"""

    def test_march_2026(self):
        """2026年3月的工作日数"""
        result = count_work_days(2026, 3)
        assert result == 22  # 31天 - 8天周末 - 1天? 需确认，但保证 > 0

    def test_february_2024_leap(self):
        """2024年2月（闰年）"""
        result = count_work_days(2024, 2)
        assert result > 0


class TestSummarizePayroll:
    """薪资汇总"""

    def test_basic_summary(self):
        result = summarize_payroll(
            base_salary_fen=500_000,
            overtime_pay_fen=12_000,
            absence_deduction_fen=40_000,
            tax_fen=5_000,
        )
        assert result["gross_salary_fen"] == 512_000
        assert result["total_deduction_fen"] == 45_000
        assert result["net_salary_fen"] == 467_000
        assert result["net_salary_yuan"] == pytest.approx(4_670.0)


class TestValidateFormula:
    """公式校验"""

    def test_valid_simple(self):
        result = validate_formula("【基本工资】*0.8")
        assert result["valid"] is True

    def test_unknown_variable(self):
        result = validate_formula("【不存在的变量】+100")
        assert result["valid"] is False
        assert any("未知变量" in e for e in result["errors"])

    def test_empty_formula(self):
        result = validate_formula("")
        assert result["valid"] is True
        assert len(result["warnings"]) > 0


class TestSafeEvalExpression:
    """安全表达式求值"""

    def test_simple_expression(self):
        result = safe_eval_expression(
            "【基本工资】*0.2",
            {"基本工资": 500_000},
        )
        assert abs(result - 100_000) <= 1

    def test_division_by_zero(self):
        """除零保护，返回 0"""
        result = safe_eval_expression("【基本工资】/0", {"基本工资": 500_000})
        assert result == 0
