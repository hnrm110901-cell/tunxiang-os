"""薪资全闭环 — V1迁入(928行) + V3合并

基本工资 + 提成 + 绩效奖金 + 加班费 + 五险一金 + 个税 + 最终实发

与 payroll_engine.py (V3纯函数) 配合：
- payroll_engine.py: 底层纯计算函数
- payroll_service.py: 业务编排层，整合考勤/排班/五险一金/个税

金额单位统一为"分"(fen)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
    count_work_days,
    derive_hourly_rate,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  五险一金费率 — 长沙 2026
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SOCIAL_INSURANCE_RATES: Dict[str, Dict[str, float]] = {
    "changsha": {
        # 养老保险
        "pension_company": 0.16,
        "pension_employee": 0.08,
        # 医疗保险
        "medical_company": 0.08,
        "medical_employee": 0.02,
        # 失业保险
        "unemployment_company": 0.007,
        "unemployment_employee": 0.003,
        # 工伤保险（餐饮业费率）
        "work_injury_company": 0.005,
        "work_injury_employee": 0.0,
        # 生育保险
        "maternity_company": 0.007,
        "maternity_employee": 0.0,
        # 住房公积金（默认8%）
        "housing_fund_company": 0.08,
        "housing_fund_employee": 0.08,
    },
}

# 长沙2026社保基数上下限（月，元 → 分）
SOCIAL_INSURANCE_BASE_LIMITS: Dict[str, Dict[str, int]] = {
    "changsha": {
        "floor_fen": 374_700,   # 下限 3747 元
        "ceiling_fen": 2_124_300,  # 上限 21243 元
    },
}

# 住房公积金基数上下限
HOUSING_FUND_BASE_LIMITS: Dict[str, Dict[str, int]] = {
    "changsha": {
        "floor_fen": 197_000,   # 下限 1970 元
        "ceiling_fen": 2_890_800,  # 上限 28908 元
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  个税税率表 — 7级超额累进（年度累计应纳税所得额，元）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TAX_BRACKETS_YUAN: List[Tuple[float, float, float]] = [
    (36_000, 0.03, 0),
    (144_000, 0.10, 2_520),
    (300_000, 0.20, 16_920),
    (420_000, 0.25, 31_920),
    (660_000, 0.30, 52_920),
    (960_000, 0.35, 85_920),
    (float("inf"), 0.45, 181_920),
]

MONTHLY_EXEMPTION_YUAN = 5_000

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  员工薪资配置（10名长沙餐厅员工）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMPLOYEE_SALARY_CONFIG: List[Dict[str, Any]] = [
    {
        "employee_id": "EMP001", "name": "张伟", "position": "店长",
        "base_salary_fen": 800_000, "position_allowance_fen": 100_000,
        "commission_rate": 0.005, "seniority_months": 33,
        "housing_fund_rate": 0.08,
    },
    {
        "employee_id": "EMP002", "name": "李娜", "position": "副店长",
        "base_salary_fen": 700_000, "position_allowance_fen": 80_000,
        "commission_rate": 0.004, "seniority_months": 18,
        "housing_fund_rate": 0.08,
    },
    {
        "employee_id": "EMP003", "name": "王强", "position": "主厨",
        "base_salary_fen": 900_000, "position_allowance_fen": 120_000,
        "commission_rate": 0.0, "seniority_months": 48,
        "housing_fund_rate": 0.08,
    },
    {
        "employee_id": "EMP004", "name": "刘洋", "position": "厨师",
        "base_salary_fen": 650_000, "position_allowance_fen": 50_000,
        "commission_rate": 0.0, "seniority_months": 26,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP005", "name": "陈静", "position": "厨师",
        "base_salary_fen": 600_000, "position_allowance_fen": 50_000,
        "commission_rate": 0.0, "seniority_months": 22,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP006", "name": "赵敏", "position": "收银员",
        "base_salary_fen": 450_000, "position_allowance_fen": 30_000,
        "commission_rate": 0.002, "seniority_months": 13,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP007", "name": "周磊", "position": "服务员",
        "base_salary_fen": 400_000, "position_allowance_fen": 20_000,
        "commission_rate": 0.003, "seniority_months": 9,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP008", "name": "孙丽", "position": "服务员",
        "base_salary_fen": 400_000, "position_allowance_fen": 20_000,
        "commission_rate": 0.003, "seniority_months": 7,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP009", "name": "吴浩", "position": "服务员",
        "base_salary_fen": 380_000, "position_allowance_fen": 0,
        "commission_rate": 0.002, "seniority_months": 2,
        "housing_fund_rate": 0.05,
    },
    {
        "employee_id": "EMP010", "name": "黄芳", "position": "迎宾",
        "base_salary_fen": 420_000, "position_allowance_fen": 20_000,
        "commission_rate": 0.002, "seniority_months": 5,
        "housing_fund_rate": 0.05,
    },
]


class PayrollService:
    """薪资全闭环 — V1迁入+V3合并

    基本工资+提成+绩效奖金+加班费+五险一金+个税+最终实发
    """

    def __init__(
        self,
        employee_configs: Optional[List[Dict[str, Any]]] = None,
        city: str = "changsha",
    ) -> None:
        configs = employee_configs or EMPLOYEE_SALARY_CONFIG
        self.employee_configs = {c["employee_id"]: c for c in configs}
        self.city = city
        self._payroll_batches: Dict[str, Dict[str, Any]] = {}
        self._batch_counter = 0

    # ──────────────────────────────────────────────────────
    #  Social Insurance
    # ──────────────────────────────────────────────────────

    def calculate_social_insurance(
        self,
        base_salary_fen: int,
        city: str = "changsha",
        housing_fund_rate: float = 0.08,
    ) -> Dict[str, Any]:
        """计算五险一金

        Changsha 2026 rates:
        - Pension: company 16% + employee 8%
        - Medical: company 8% + employee 2%
        - Unemployment: company 0.7% + employee 0.3%
        - Work injury: company 0.5% (restaurant)
        - Maternity: company 0.7%
        - Housing fund: both 5-12% (default 8%)

        Args:
            base_salary_fen: 缴费基数（分），会被限制在上下限内
            city: 城市
            housing_fund_rate: 公积金缴存比例 (0.05~0.12)
        """
        rates = SOCIAL_INSURANCE_RATES.get(city, SOCIAL_INSURANCE_RATES["changsha"])
        base_limits = SOCIAL_INSURANCE_BASE_LIMITS.get(city, SOCIAL_INSURANCE_BASE_LIMITS["changsha"])
        hf_limits = HOUSING_FUND_BASE_LIMITS.get(city, HOUSING_FUND_BASE_LIMITS["changsha"])

        # Clamp social insurance base
        si_base = max(base_limits["floor_fen"], min(base_salary_fen, base_limits["ceiling_fen"]))
        # Clamp housing fund base
        hf_base = max(hf_limits["floor_fen"], min(base_salary_fen, hf_limits["ceiling_fen"]))
        # Clamp housing fund rate
        housing_fund_rate = max(0.05, min(housing_fund_rate, 0.12))

        # Calculate each item
        pension_company = int(si_base * rates["pension_company"])
        pension_employee = int(si_base * rates["pension_employee"])
        medical_company = int(si_base * rates["medical_company"])
        medical_employee = int(si_base * rates["medical_employee"])
        unemployment_company = int(si_base * rates["unemployment_company"])
        unemployment_employee = int(si_base * rates["unemployment_employee"])
        work_injury_company = int(si_base * rates["work_injury_company"])
        work_injury_employee = 0
        maternity_company = int(si_base * rates["maternity_company"])
        maternity_employee = 0

        housing_fund_company = int(hf_base * housing_fund_rate)
        housing_fund_employee = int(hf_base * housing_fund_rate)

        total_company = (
            pension_company + medical_company + unemployment_company
            + work_injury_company + maternity_company + housing_fund_company
        )
        total_employee = (
            pension_employee + medical_employee + unemployment_employee
            + work_injury_employee + maternity_employee + housing_fund_employee
        )

        return {
            "si_base_fen": si_base,
            "hf_base_fen": hf_base,
            "pension": {
                "company_fen": pension_company, "employee_fen": pension_employee,
                "company_rate": rates["pension_company"], "employee_rate": rates["pension_employee"],
            },
            "medical": {
                "company_fen": medical_company, "employee_fen": medical_employee,
                "company_rate": rates["medical_company"], "employee_rate": rates["medical_employee"],
            },
            "unemployment": {
                "company_fen": unemployment_company, "employee_fen": unemployment_employee,
                "company_rate": rates["unemployment_company"], "employee_rate": rates["unemployment_employee"],
            },
            "work_injury": {
                "company_fen": work_injury_company, "employee_fen": work_injury_employee,
                "company_rate": rates["work_injury_company"], "employee_rate": 0.0,
            },
            "maternity": {
                "company_fen": maternity_company, "employee_fen": maternity_employee,
                "company_rate": rates["maternity_company"], "employee_rate": 0.0,
            },
            "housing_fund": {
                "company_fen": housing_fund_company, "employee_fen": housing_fund_employee,
                "rate": housing_fund_rate,
            },
            "total_company_fen": total_company,
            "total_employee_fen": total_employee,
            "total_company_yuan": round(total_company / 100, 2),
            "total_employee_yuan": round(total_employee / 100, 2),
        }

    # ──────────────────────────────────────────────────────
    #  Tax
    # ──────────────────────────────────────────────────────

    def calculate_tax(
        self,
        annual_taxable_income_fen: int,
    ) -> Dict[str, Any]:
        """计算年度累计个税（7级超额累进）

        0-36000: 3%, 36000-144000: 10%, 144000-300000: 20%,
        300000-420000: 25%, 420000-660000: 30%, 660000-960000: 35%, 960000+: 45%

        Args:
            annual_taxable_income_fen: 年度累计应纳税所得额（分）
        """
        income_yuan = annual_taxable_income_fen / 100

        if income_yuan <= 0:
            return {
                "annual_taxable_income_fen": annual_taxable_income_fen,
                "annual_taxable_income_yuan": 0,
                "tax_yuan": 0,
                "tax_fen": 0,
                "rate": 0,
                "quick_deduction_yuan": 0,
            }

        tax_yuan = 0.0
        rate = 0.0
        quick_deduction = 0.0
        for upper, r, qd in TAX_BRACKETS_YUAN:
            if income_yuan <= upper:
                tax_yuan = income_yuan * r - qd
                rate = r
                quick_deduction = qd
                break

        tax_yuan = max(0, tax_yuan)

        return {
            "annual_taxable_income_fen": annual_taxable_income_fen,
            "annual_taxable_income_yuan": income_yuan,
            "tax_yuan": round(tax_yuan, 2),
            "tax_fen": int(tax_yuan * 100),
            "rate": rate,
            "quick_deduction_yuan": quick_deduction,
        }

    def _calculate_monthly_tax(
        self,
        monthly_taxable_income_yuan: float,
        month_index: int,
        cumulative_prev_income_yuan: float = 0,
        cumulative_prev_tax_yuan: float = 0,
        social_insurance_yuan: float = 0,
        housing_fund_yuan: float = 0,
        special_deduction_yuan: float = 0,
    ) -> Dict[str, Any]:
        """累计预扣法计算当月个税

        Monthly = (cumulative tax - previous months paid)
        """
        cumulative_income = cumulative_prev_income_yuan + monthly_taxable_income_yuan
        cumulative_exemption = MONTHLY_EXEMPTION_YUAN * month_index
        cumulative_deductions = (social_insurance_yuan + housing_fund_yuan + special_deduction_yuan) * month_index
        cumulative_taxable = max(0, cumulative_income - cumulative_exemption - cumulative_deductions)

        # Apply tax brackets
        cumulative_tax = 0.0
        rate_applied = 0.0
        for upper, r, qd in TAX_BRACKETS_YUAN:
            if cumulative_taxable <= upper:
                cumulative_tax = cumulative_taxable * r - qd
                rate_applied = r
                break

        cumulative_tax = max(0, cumulative_tax)
        monthly_tax = max(0, cumulative_tax - cumulative_prev_tax_yuan)

        return {
            "cumulative_income_yuan": cumulative_income,
            "cumulative_taxable_yuan": cumulative_taxable,
            "cumulative_tax_yuan": round(cumulative_tax, 2),
            "monthly_tax_yuan": round(monthly_tax, 2),
            "monthly_tax_fen": int(monthly_tax * 100),
            "rate": rate_applied,
        }

    # ──────────────────────────────────────────────────────
    #  Employee Payroll
    # ──────────────────────────────────────────────────────

    def calculate_employee_payroll(
        self,
        employee_id: str,
        month: str,
        attendance_data: Optional[Dict[str, Any]] = None,
        overtime_data: Optional[Dict[str, Any]] = None,
        sales_amount_fen: int = 0,
        performance_coefficient: float = 1.0,
        month_index: int = 1,
        cumulative_prev_income_yuan: float = 0,
        cumulative_prev_tax_yuan: float = 0,
    ) -> Dict[str, Any]:
        """计算单个员工月薪

        Detail:
        base_salary + position_allowance + attendance_bonus
        + sales_commission (based on personal sales if waiter)
        + overtime_pay (1.5x weekday, 2x weekend, 3x holiday)
        + performance_bonus
        - social_insurance (employee portion)
        - housing_fund (employee portion)
        - personal_income_tax (tiered progressive)
        = net_pay
        """
        config = self.employee_configs.get(employee_id)
        if not config:
            return {"ok": False, "error": f"Employee {employee_id} not found"}

        year = int(month.split("-")[0])
        mon = int(month.split("-")[1])
        work_days_in_month = count_work_days(year, mon)

        base_salary = config["base_salary_fen"]
        position_allowance = config.get("position_allowance_fen", 0)

        # Default attendance data
        if attendance_data is None:
            attendance_data = {
                "attendance_days": work_days_in_month,
                "absence_days": 0,
                "late_count": 0,
                "early_leave_count": 0,
            }
        if overtime_data is None:
            overtime_data = {
                "weekday_hours": 0,
                "weekend_hours": 0,
                "holiday_hours": 0,
            }

        attendance_days = attendance_data.get("attendance_days", work_days_in_month)
        absence_days = attendance_data.get("absence_days", 0)
        late_count = attendance_data.get("late_count", 0)
        early_leave_count = attendance_data.get("early_leave_count", 0)

        # 1. Base salary (prorated)
        base_pay = compute_base_salary(base_salary, attendance_days, work_days_in_month)

        # 2. Commission
        commission_rate = config.get("commission_rate", 0)
        commission = compute_commission(sales_amount_fen, commission_rate)

        # 3. Overtime pay
        hourly_rate = derive_hourly_rate(base_salary, work_days_in_month)
        ot_weekday = compute_overtime_pay(hourly_rate, overtime_data.get("weekday_hours", 0), "weekday")
        ot_weekend = compute_overtime_pay(hourly_rate, overtime_data.get("weekend_hours", 0), "weekend")
        ot_holiday = compute_overtime_pay(hourly_rate, overtime_data.get("holiday_hours", 0), "holiday")
        total_overtime_pay = ot_weekday + ot_weekend + ot_holiday

        # 4. Performance bonus
        perf_bonus = compute_performance_bonus(base_salary, performance_coefficient)

        # 5. Seniority subsidy
        seniority_sub = compute_seniority_subsidy(config.get("seniority_months", 0))

        # 6. Full attendance bonus (300 yuan)
        full_attendance = compute_full_attendance_bonus(
            absence_days, late_count, early_leave_count, 30_000
        )

        # 7. Deductions: late / early / absence
        absence_ded = compute_absence_deduction(base_salary, absence_days, work_days_in_month)
        late_ded = compute_late_deduction(late_count, 5_000)  # 50 yuan per late
        early_ded = compute_early_leave_deduction(early_leave_count, 5_000)

        # 8. Social insurance
        hf_rate = config.get("housing_fund_rate", 0.08)
        si = self.calculate_social_insurance(base_salary, self.city, hf_rate)
        si_employee = si["total_employee_fen"]
        # Separate for tax deduction
        si_pension_emp = si["pension"]["employee_fen"]
        si_medical_emp = si["medical"]["employee_fen"]
        si_unemployment_emp = si["unemployment"]["employee_fen"]
        hf_employee = si["housing_fund"]["employee_fen"]
        social_insurance_only = si_pension_emp + si_medical_emp + si_unemployment_emp

        # 9. Gross salary (before tax)
        gross = (
            base_pay + position_allowance + commission
            + total_overtime_pay + perf_bonus + seniority_sub + full_attendance
        )

        # 10. Pre-tax deductions
        pre_tax_deductions = absence_ded + late_ded + early_ded

        # Taxable income = gross - pre_tax_deductions - social_insurance_employee - housing_fund
        taxable_income_fen = gross - pre_tax_deductions - social_insurance_only - hf_employee
        taxable_income_yuan = max(0, taxable_income_fen / 100)

        # 11. Tax calculation (cumulative withholding)
        tax_result = self._calculate_monthly_tax(
            monthly_taxable_income_yuan=taxable_income_yuan,
            month_index=month_index,
            cumulative_prev_income_yuan=cumulative_prev_income_yuan,
            cumulative_prev_tax_yuan=cumulative_prev_tax_yuan,
            social_insurance_yuan=social_insurance_only / 100,
            housing_fund_yuan=hf_employee / 100,
        )
        tax_fen = tax_result["monthly_tax_fen"]

        # 12. Net pay
        total_deduction = pre_tax_deductions + si_employee + tax_fen
        net_pay = gross - total_deduction

        return {
            "ok": True,
            "employee_id": employee_id,
            "name": config["name"],
            "position": config["position"],
            "month": month,
            "work_days_in_month": work_days_in_month,
            "attendance_days": attendance_days,

            # Income items
            "base_pay_fen": base_pay,
            "position_allowance_fen": position_allowance,
            "commission_fen": commission,
            "overtime_pay_fen": total_overtime_pay,
            "overtime_detail": {
                "weekday_fen": ot_weekday,
                "weekend_fen": ot_weekend,
                "holiday_fen": ot_holiday,
                "hourly_rate_fen": hourly_rate,
            },
            "performance_bonus_fen": perf_bonus,
            "seniority_subsidy_fen": seniority_sub,
            "full_attendance_bonus_fen": full_attendance,

            # Gross
            "gross_salary_fen": gross,
            "gross_salary_yuan": round(gross / 100, 2),

            # Deductions
            "absence_deduction_fen": absence_ded,
            "late_deduction_fen": late_ded,
            "early_leave_deduction_fen": early_ded,
            "social_insurance_employee_fen": social_insurance_only,
            "housing_fund_employee_fen": hf_employee,
            "tax_fen": tax_fen,
            "tax_detail": tax_result,

            # Social insurance full detail
            "social_insurance_detail": si,

            # Net
            "total_deduction_fen": total_deduction,
            "total_deduction_yuan": round(total_deduction / 100, 2),
            "net_pay_fen": net_pay,
            "net_pay_yuan": round(net_pay / 100, 2),
        }

    # ──────────────────────────────────────────────────────
    #  Store Payroll (batch)
    # ──────────────────────────────────────────────────────

    def calculate_payroll(
        self,
        store_id: str,
        month: str,
        attendance_map: Optional[Dict[str, Dict]] = None,
        overtime_map: Optional[Dict[str, Dict]] = None,
        sales_map: Optional[Dict[str, int]] = None,
        performance_map: Optional[Dict[str, float]] = None,
        month_index: int = 1,
    ) -> Dict[str, Any]:
        """全店月度薪资计算

        Returns: {batch_id, employees: [{...payroll_detail...}], total_cost}
        """
        attendance_map = attendance_map or {}
        overtime_map = overtime_map or {}
        sales_map = sales_map or {}
        performance_map = performance_map or {}

        self._batch_counter += 1
        batch_id = f"PAY-{store_id}-{month}-{self._batch_counter:04d}"

        employees_result: List[Dict[str, Any]] = []
        total_gross = 0
        total_net = 0
        total_company_si = 0

        for emp_id, config in self.employee_configs.items():
            payroll = self.calculate_employee_payroll(
                employee_id=emp_id,
                month=month,
                attendance_data=attendance_map.get(emp_id),
                overtime_data=overtime_map.get(emp_id),
                sales_amount_fen=sales_map.get(emp_id, 0),
                performance_coefficient=performance_map.get(emp_id, 1.0),
                month_index=month_index,
            )
            if payroll.get("ok"):
                employees_result.append(payroll)
                total_gross += payroll["gross_salary_fen"]
                total_net += payroll["net_pay_fen"]
                total_company_si += payroll["social_insurance_detail"]["total_company_fen"]

        total_labor_cost = total_gross + total_company_si

        result = {
            "batch_id": batch_id,
            "store_id": store_id,
            "month": month,
            "status": "draft",
            "employee_count": len(employees_result),
            "employees": employees_result,
            "summary": {
                "total_gross_fen": total_gross,
                "total_gross_yuan": round(total_gross / 100, 2),
                "total_net_fen": total_net,
                "total_net_yuan": round(total_net / 100, 2),
                "total_company_si_fen": total_company_si,
                "total_labor_cost_fen": total_labor_cost,
                "total_labor_cost_yuan": round(total_labor_cost / 100, 2),
            },
            "created_at": datetime.now().isoformat(),
        }

        self._payroll_batches[batch_id] = result
        return result

    # ──────────────────────────────────────────────────────
    #  Payslip
    # ──────────────────────────────────────────────────────

    def generate_payslip(
        self,
        employee_id: str,
        month: str,
        payroll_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成工资条

        Formatted payslip with all items
        """
        if payroll_data is None:
            payroll_data = self.calculate_employee_payroll(employee_id, month)

        if not payroll_data.get("ok"):
            return payroll_data

        p = payroll_data

        income_items = [
            {"item": "基本工资", "amount_fen": p["base_pay_fen"]},
            {"item": "岗位补贴", "amount_fen": p["position_allowance_fen"]},
            {"item": "销售提成", "amount_fen": p["commission_fen"]},
            {"item": "加班费", "amount_fen": p["overtime_pay_fen"]},
            {"item": "绩效奖金", "amount_fen": p["performance_bonus_fen"]},
            {"item": "工龄补贴", "amount_fen": p["seniority_subsidy_fen"]},
            {"item": "全勤奖", "amount_fen": p["full_attendance_bonus_fen"]},
        ]

        deduction_items = [
            {"item": "缺勤扣款", "amount_fen": p["absence_deduction_fen"]},
            {"item": "迟到扣款", "amount_fen": p["late_deduction_fen"]},
            {"item": "早退扣款", "amount_fen": p["early_leave_deduction_fen"]},
            {"item": "养老保险(个人)", "amount_fen": p["social_insurance_detail"]["pension"]["employee_fen"]},
            {"item": "医疗保险(个人)", "amount_fen": p["social_insurance_detail"]["medical"]["employee_fen"]},
            {"item": "失业保险(个人)", "amount_fen": p["social_insurance_detail"]["unemployment"]["employee_fen"]},
            {"item": "住房公积金(个人)", "amount_fen": p["housing_fund_employee_fen"]},
            {"item": "个人所得税", "amount_fen": p["tax_fen"]},
        ]

        # Add yuan amounts
        for item in income_items + deduction_items:
            item["amount_yuan"] = round(item["amount_fen"] / 100, 2)

        return {
            "employee_id": employee_id,
            "name": p["name"],
            "position": p["position"],
            "month": month,
            "income_items": income_items,
            "deduction_items": deduction_items,
            "gross_salary_yuan": p["gross_salary_yuan"],
            "total_deduction_yuan": p["total_deduction_yuan"],
            "net_pay_yuan": p["net_pay_yuan"],
            "generated_at": datetime.now().isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  Approve / History / Labor Cost
    # ──────────────────────────────────────────────────────

    def approve_payroll(
        self,
        batch_id: str,
        approved_by: str,
    ) -> Dict[str, Any]:
        """审批薪资批次"""
        batch = self._payroll_batches.get(batch_id)
        if not batch:
            return {"ok": False, "error": f"Batch {batch_id} not found"}

        if batch["status"] != "draft":
            return {"ok": False, "error": f"Batch is already {batch['status']}"}

        batch["status"] = "approved"
        batch["approved_by"] = approved_by
        batch["approved_at"] = datetime.now().isoformat()

        return {
            "ok": True,
            "batch_id": batch_id,
            "status": "approved",
            "approved_by": approved_by,
        }

    def get_payroll_history(
        self,
        employee_id: str,
        months: int = 12,
    ) -> List[Dict[str, Any]]:
        """查询员工薪资历史"""
        history: List[Dict[str, Any]] = []
        for batch_id, batch in self._payroll_batches.items():
            for emp_data in batch.get("employees", []):
                if emp_data.get("employee_id") == employee_id:
                    history.append({
                        "batch_id": batch_id,
                        "month": batch["month"],
                        "status": batch["status"],
                        "gross_salary_yuan": emp_data.get("gross_salary_yuan", 0),
                        "net_pay_yuan": emp_data.get("net_pay_yuan", 0),
                    })
        return history[-months:]

    def get_store_labor_cost(
        self,
        store_id: str,
        month: str,
        revenue_fen: int = 0,
    ) -> Dict[str, Any]:
        """门店人力成本分析

        Total labor cost, labor_cost_rate (vs revenue), per-employee cost
        """
        # Find the batch for this store/month
        target_batch = None
        for batch_id, batch in self._payroll_batches.items():
            if batch["store_id"] == store_id and batch["month"] == month:
                target_batch = batch
                break

        if not target_batch:
            # Calculate on the fly
            target_batch = self.calculate_payroll(store_id, month)

        summary = target_batch.get("summary", {})
        total_labor = summary.get("total_labor_cost_fen", 0)
        emp_count = target_batch.get("employee_count", 1)

        labor_cost_rate = 0.0
        if revenue_fen > 0:
            labor_cost_rate = round(total_labor / revenue_fen * 100, 2)

        per_employee_cost = int(total_labor / emp_count) if emp_count > 0 else 0

        return {
            "store_id": store_id,
            "month": month,
            "total_labor_cost_fen": total_labor,
            "total_labor_cost_yuan": round(total_labor / 100, 2),
            "employee_count": emp_count,
            "per_employee_cost_fen": per_employee_cost,
            "per_employee_cost_yuan": round(per_employee_cost / 100, 2),
            "revenue_fen": revenue_fen,
            "labor_cost_rate_pct": labor_cost_rate,
        }
