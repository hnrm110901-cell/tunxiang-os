"""薪资计算引擎 V2 — 全链路计算（五险一金 + 个税 + DB 持久化）

与现有 payroll_engine.py（纯函数层）配合：
- payroll_engine.py: 底层纯计算函数（考勤/加班/提成/绩效）
- payroll_engine_v2.py (本模块): 业务编排层，整合社保/个税/DB读写

tenant_id 显式传入，不依赖 session 变量。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from services.payroll_engine import (
    compute_base_salary,
    compute_commission,
    compute_full_attendance_bonus,
    compute_absence_deduction,
    compute_late_deduction,
    compute_early_leave_deduction,
    compute_performance_bonus,
    compute_seniority_subsidy,
    compute_overtime_pay,
    derive_hourly_rate,
    count_work_days,
)
from services.social_insurance import SocialInsuranceCalculator
from services.income_tax import IncomeTaxCalculator
from models.payroll_record import PayrollRecord, PayrollRecordStatus, StoreSalarySummary


class PayrollEngine:
    """薪资计算引擎

    compute_monthly: 计算单个员工月度薪资
    batch_compute: 批量计算门店所有员工薪资
    """

    def __init__(self, city: str = "changsha") -> None:
        self.si_calculator = SocialInsuranceCalculator(city=city)
        self.tax_calculator = IncomeTaxCalculator()

    # ── 核心计算 ────────────────────────────────────────────────────────────

    def compute_monthly(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        store_id: str,
        payroll_month: str,
        # 薪资方案参数
        base_salary_fen: int,
        work_days_in_month: Optional[int] = None,
        # 考勤数据
        attendance_days: int = 0,
        absence_days: float = 0,
        late_count: int = 0,
        early_leave_count: int = 0,
        late_deduction_per_time_fen: int = 5_000,
        early_leave_deduction_per_time_fen: int = 5_000,
        # 加班数据
        overtime_weekday_hours: float = 0,
        overtime_weekend_hours: float = 0,
        overtime_holiday_hours: float = 0,
        # 销售提成
        sales_amount_fen: int = 0,
        commission_rate: float = 0.0,
        # 绩效
        performance_coefficient: float = 1.0,
        seniority_months: int = 0,
        full_attendance_bonus_fen: int = 30_000,
        # 补贴
        position_allowance_fen: int = 0,
        meal_allowance_fen: int = 0,
        transport_allowance_fen: int = 0,
        extra_bonus_fen: int = 0,
        # 社保配置
        housing_fund_rate: Optional[float] = None,
        city_config: Optional[Dict[str, Any]] = None,
        # 个税累计数据（年初至今，不含当月）
        ytd_income_yuan: float = 0.0,
        ytd_tax_paid_yuan: float = 0.0,
        ytd_social_insurance_yuan: float = 0.0,
        month_index: int = 1,
        special_deduction_monthly_yuan: float = 0.0,
    ) -> PayrollRecord:
        """计算单个员工月度薪资，返回 PayrollRecord

        所有金额内部以"分"计算，最终存储时转为"元"（NUMERIC(10,2)）。

        Args:
            tenant_id: 租户 ID（多租户隔离）
            employee_id: 员工 ID
            store_id: 门店 ID
            payroll_month: 薪资月份（YYYY-MM）
            base_salary_fen: 月薪标准（分）
            work_days_in_month: 当月工作日数（None 时自动计算）
            attendance_days: 实际出勤天数
            absence_days: 缺勤天数
            late_count: 迟到次数
            early_leave_count: 早退次数
            late_deduction_per_time_fen: 每次迟到扣款（分）
            early_leave_deduction_per_time_fen: 每次早退扣款（分）
            overtime_weekday_hours: 工作日加班小时数
            overtime_weekend_hours: 周末加班小时数
            overtime_holiday_hours: 法定节假日加班小时数
            sales_amount_fen: 当月销售额（分），用于提成计算
            commission_rate: 提成比例（如 0.05 = 5%）
            performance_coefficient: 绩效系数（1.0=无奖金，1.2=基本工资×20%奖金）
            seniority_months: 司龄月数，用于工龄补贴
            full_attendance_bonus_fen: 全勤奖金额（分）
            position_allowance_fen: 岗位补贴（分）
            meal_allowance_fen: 餐补（分）
            transport_allowance_fen: 交通补贴（分）
            extra_bonus_fen: 其他奖金（分）
            housing_fund_rate: 公积金个人缴存比例覆盖
            city_config: 额外城市配置覆盖
            ytd_income_yuan: 年初至今（不含当月）累计应税收入（元）
            ytd_tax_paid_yuan: 年初至今已预缴税款（元）
            ytd_social_insurance_yuan: 年初至今（不含当月）社保+公积金个人部分（元）
            month_index: 当年第几个月（1-12）
            special_deduction_monthly_yuan: 月专项附加扣除（元）

        Returns:
            PayrollRecord（草稿状态，包含完整计算明细）
        """
        year, mon = int(payroll_month.split("-")[0]), int(payroll_month.split("-")[1])
        if work_days_in_month is None:
            work_days_in_month = count_work_days(year, mon)

        # ── 1. 考勤相关计算 ────────────────────────────────────────────────
        base_pay_fen = compute_base_salary(base_salary_fen, attendance_days, work_days_in_month)
        absence_deduction_fen = compute_absence_deduction(base_salary_fen, absence_days, work_days_in_month)
        late_deduction_fen = compute_late_deduction(late_count, late_deduction_per_time_fen)
        early_leave_deduction_fen = compute_early_leave_deduction(early_leave_count, early_leave_deduction_per_time_fen)

        # ── 2. 加班费 ──────────────────────────────────────────────────────
        hourly_rate_fen = derive_hourly_rate(base_salary_fen, work_days_in_month)
        overtime_weekday_fen = compute_overtime_pay(hourly_rate_fen, overtime_weekday_hours, "weekday")
        overtime_weekend_fen = compute_overtime_pay(hourly_rate_fen, overtime_weekend_hours, "weekend")
        overtime_holiday_fen = compute_overtime_pay(hourly_rate_fen, overtime_holiday_hours, "holiday")
        total_overtime_fen = overtime_weekday_fen + overtime_weekend_fen + overtime_holiday_fen

        # ── 3. 提成 ────────────────────────────────────────────────────────
        commission_fen = compute_commission(sales_amount_fen, commission_rate)

        # ── 4. 绩效奖金和工龄补贴 ──────────────────────────────────────────
        perf_bonus_fen = compute_performance_bonus(base_salary_fen, performance_coefficient)
        seniority_sub_fen = compute_seniority_subsidy(seniority_months)

        # ── 5. 全勤奖 ──────────────────────────────────────────────────────
        full_attend_fen = compute_full_attendance_bonus(
            absence_days, late_count, early_leave_count, full_attendance_bonus_fen
        )

        # ── 6. 补贴合计 ────────────────────────────────────────────────────
        allowances_fen = position_allowance_fen + meal_allowance_fen + transport_allowance_fen

        # ── 7. 应发工资（考勤扣款前的收入总和） ───────────────────────────────
        gross_fen = (
            base_pay_fen
            + total_overtime_fen
            + commission_fen
            + perf_bonus_fen
            + seniority_sub_fen
            + full_attend_fen
            + allowances_fen
            + extra_bonus_fen
        )
        # 考勤扣款从应发中扣除
        attendance_total_deduction_fen = absence_deduction_fen + late_deduction_fen + early_leave_deduction_fen
        gross_after_attendance_fen = max(0, gross_fen - attendance_total_deduction_fen)

        # ── 8. 五险一金 ────────────────────────────────────────────────────
        # 以应发工资（gross_fen）作为社保缴费基数（按实际工资，不含考勤扣款）
        si_result = self.si_calculator.calculate(
            gross_salary_fen=base_salary_fen,  # 社保基数通常用合同工资
            city_config=city_config,
            housing_fund_rate_override=housing_fund_rate,
        )
        si_personal_fen = si_result["personal_total"]
        si_company_fen = si_result["company_total"]

        # ── 9. 个税（累计预扣法） ──────────────────────────────────────────
        # 应税收入 = 应发 - 考勤扣款 - 个人社保（税前扣除）
        monthly_taxable_income_yuan = max(
            0.0,
            (gross_after_attendance_fen - si_personal_fen) / 100.0,
        )

        # 累计社保：前几月已缴 + 当月
        current_si_yuan = si_personal_fen / 100.0
        ytd_si_total_yuan = ytd_social_insurance_yuan + current_si_yuan

        tax_result = self.tax_calculator.calculate_monthly(
            current_month_income=monthly_taxable_income_yuan,
            ytd_income=ytd_income_yuan,
            ytd_tax_paid=ytd_tax_paid_yuan,
            ytd_social_insurance=ytd_si_total_yuan,
            month_index=month_index,
            special_deduction_monthly=special_deduction_monthly_yuan,
        )
        income_tax_fen = int(tax_result["monthly_tax"] * 100)

        # ── 10. 实发工资 ───────────────────────────────────────────────────
        net_fen = gross_after_attendance_fen - si_personal_fen - income_tax_fen
        net_fen = max(0, net_fen)

        # ── 11. 组装详细明细（用于审计） ─────────────────────────────────────
        details: Dict[str, Any] = {
            "work_days_in_month": work_days_in_month,
            "attendance_days": attendance_days,
            "income": {
                "base_pay_fen": base_pay_fen,
                "base_salary_contract_fen": base_salary_fen,
                "overtime": {
                    "weekday_fen": overtime_weekday_fen,
                    "weekend_fen": overtime_weekend_fen,
                    "holiday_fen": overtime_holiday_fen,
                    "total_fen": total_overtime_fen,
                    "hourly_rate_fen": hourly_rate_fen,
                },
                "commission_fen": commission_fen,
                "commission_rate": commission_rate,
                "sales_amount_fen": sales_amount_fen,
                "performance_bonus_fen": perf_bonus_fen,
                "performance_coefficient": performance_coefficient,
                "seniority_subsidy_fen": seniority_sub_fen,
                "seniority_months": seniority_months,
                "full_attendance_bonus_fen": full_attend_fen,
                "allowances": {
                    "position_fen": position_allowance_fen,
                    "meal_fen": meal_allowance_fen,
                    "transport_fen": transport_allowance_fen,
                    "extra_bonus_fen": extra_bonus_fen,
                    "total_fen": allowances_fen + extra_bonus_fen,
                },
            },
            "deductions": {
                "absence": {
                    "days": absence_days,
                    "fen": absence_deduction_fen,
                },
                "late": {
                    "count": late_count,
                    "fen": late_deduction_fen,
                },
                "early_leave": {
                    "count": early_leave_count,
                    "fen": early_leave_deduction_fen,
                },
                "attendance_total_fen": attendance_total_deduction_fen,
            },
            "social_insurance": {
                **si_result,
                "personal_total_fen": si_personal_fen,
                "company_total_fen": si_company_fen,
            },
            "income_tax": {
                **tax_result,
                "monthly_tax_fen": income_tax_fen,
                "monthly_taxable_income_yuan": monthly_taxable_income_yuan,
            },
            "summary": {
                "gross_fen": gross_fen,
                "attendance_deduction_fen": attendance_total_deduction_fen,
                "gross_after_attendance_fen": gross_after_attendance_fen,
                "si_personal_fen": si_personal_fen,
                "income_tax_fen": income_tax_fen,
                "net_fen": net_fen,
            },
            "computed_at": datetime.now().isoformat(),
        }

        return PayrollRecord(
            tenant_id=UUID(tenant_id),
            employee_id=UUID(employee_id),
            store_id=UUID(store_id),
            payroll_month=payroll_month,
            base_salary=round(base_salary_fen / 100, 2),
            attendance_days=attendance_days,
            attendance_deduction=round(attendance_total_deduction_fen / 100, 2),
            commission=round(commission_fen / 100, 2),
            bonus=round((perf_bonus_fen + extra_bonus_fen) / 100, 2),
            allowances=round((allowances_fen + seniority_sub_fen + full_attend_fen) / 100, 2),
            gross_salary=round(gross_fen / 100, 2),
            social_insurance_personal=round(si_personal_fen / 100, 2),
            income_tax=round(income_tax_fen / 100, 2),
            net_salary=round(net_fen / 100, 2),
            social_insurance_company=round(si_company_fen / 100, 2),
            details=details,
            status=PayrollRecordStatus.DRAFT,
        )

    def batch_compute(
        self,
        *,
        tenant_id: str,
        store_id: str,
        payroll_month: str,
        employees: List[Dict[str, Any]],
    ) -> StoreSalarySummary:
        """批量计算门店所有员工工资

        Args:
            tenant_id: 租户 ID
            store_id: 门店 ID
            payroll_month: 薪资月份（YYYY-MM）
            employees: 员工参数列表，每项为 compute_monthly 的 kwargs（不含 tenant_id/store_id/payroll_month）

        Returns:
            StoreSalarySummary（含所有 PayrollRecord 和门店汇总数据）
        """
        records: List[PayrollRecord] = []
        errors: List[Dict[str, Any]] = []

        for emp_params in employees:
            emp_id = emp_params.get("employee_id", "unknown")
            try:
                record = self.compute_monthly(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    payroll_month=payroll_month,
                    **{k: v for k, v in emp_params.items() if k not in ("tenant_id", "store_id", "payroll_month")},
                )
                records.append(record)
            except (ValueError, KeyError, ZeroDivisionError) as exc:
                errors.append({"employee_id": emp_id, "error": str(exc)})

        total_gross = sum(r.gross_salary for r in records)
        total_net = sum(r.net_salary for r in records)
        total_si_personal = sum(r.social_insurance_personal or 0 for r in records)
        total_si_company = sum(r.social_insurance_company or 0 for r in records)
        total_tax = sum(r.income_tax for r in records)
        total_labor_cost = total_gross + total_si_company

        return StoreSalarySummary(
            store_id=store_id,
            payroll_month=payroll_month,
            tenant_id=tenant_id,
            employee_count=len(records),
            total_gross_yuan=round(total_gross, 2),
            total_net_yuan=round(total_net, 2),
            total_social_insurance_personal_yuan=round(total_si_personal, 2),
            total_social_insurance_company_yuan=round(total_si_company, 2),
            total_income_tax_yuan=round(total_tax, 2),
            total_labor_cost_yuan=round(total_labor_cost, 2),
            records=records,
        )
