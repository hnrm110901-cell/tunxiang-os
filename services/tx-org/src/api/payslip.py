"""工资条 API

提供工资条的批量生成、列表查询和员工个人工资条查询。
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_monthly_tax,
    compute_overtime_pay,
    compute_performance_bonus,
    compute_seniority_subsidy,
    count_work_days,
    derive_hourly_rate,
    summarize_payroll,
)

router = APIRouter(prefix="/api/v1/org", tags=["payslips"])


# ── 内存存储（生产环境替换为 DB） ──

_payslip_store: dict[str, list[dict]] = {}
# key = "{store_id}:{month}", value = list of payslip dicts


# ── 请求/响应模型 ──


class GeneratePayslipsReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    month: str = Field(
        ...,
        description="月份，格式 YYYY-MM，如 2026-03",
        pattern=r"^\d{4}-\d{2}$",
    )
    employees: list[dict] = Field(
        ...,
        description=(
            "员工列表，每项含: employee_id, name, role, "
            "base_salary_fen, attendance_days, absence_days, "
            "late_count, early_leave_count, overtime_hours, overtime_type, "
            "performance_coefficient, seniority_months, sales_amount_fen, "
            "commission_rate, position_allowance_fen, meal_allowance_fen, "
            "transport_allowance_fen, enabled_items(可选)"
        ),
    )


class PayslipQuery(BaseModel):
    store_id: str
    month: str


# ── 工具函数 ──


def _build_payslip(employee: dict, month: str) -> dict:
    """根据员工数据和薪资引擎计算生成单条工资条。"""
    year, mon = int(month.split("-")[0]), int(month.split("-")[1])
    work_days = count_work_days(year, mon)

    base_fen = employee.get("base_salary_fen", 0)
    attendance = employee.get("attendance_days", work_days)
    absence = employee.get("absence_days", 0)
    late_count = employee.get("late_count", 0)
    early_leave = employee.get("early_leave_count", 0)
    overtime_hours = employee.get("overtime_hours", 0)
    overtime_type = employee.get("overtime_type", "weekday")
    perf_coeff = employee.get("performance_coefficient", 1.0)
    seniority = employee.get("seniority_months", 0)
    position_allowance = employee.get("position_allowance_fen", 0)
    meal_allowance = employee.get("meal_allowance_fen", 0)
    transport_allowance = employee.get("transport_allowance_fen", 0)

    # 计算各项
    base_salary = compute_base_salary(base_fen, attendance, work_days)
    hourly_rate = derive_hourly_rate(base_fen, work_days)
    overtime_pay = compute_overtime_pay(hourly_rate, overtime_hours, overtime_type)
    absence_deduction = compute_absence_deduction(base_fen, absence, work_days)
    late_deduction = compute_late_deduction(late_count, 5000)  # 50 元/次
    perf_bonus = compute_performance_bonus(base_fen, perf_coeff)
    seniority_sub = compute_seniority_subsidy(seniority)
    full_attend = compute_full_attendance_bonus(absence, late_count, early_leave, 30000)

    # 社保公积金（简化：按基本工资比例估算）
    social_insurance = int(base_salary * 0.105)  # 个人 10.5%
    housing_fund = int(base_salary * 0.07)       # 个人 7%

    # 个税
    gross_yuan = (
        base_salary + position_allowance + meal_allowance + transport_allowance
        + perf_bonus + overtime_pay + seniority_sub + full_attend
    ) / 100
    tax_yuan = compute_monthly_tax(
        current_month_taxable_income_yuan=gross_yuan,
        cumulative_prev_taxable_income_yuan=0,
        cumulative_prev_tax_yuan=0,
        social_insurance_yuan=social_insurance / 100,
        housing_fund_yuan=housing_fund / 100,
        month_index=mon,
    )
    tax_fen = int(tax_yuan * 100)

    summary = summarize_payroll(
        base_salary_fen=base_salary,
        position_allowance_fen=position_allowance,
        meal_allowance_fen=meal_allowance,
        transport_allowance_fen=transport_allowance,
        performance_bonus_fen=perf_bonus,
        overtime_pay_fen=overtime_pay,
        seniority_subsidy_fen=seniority_sub,
        full_attendance_bonus_fen=full_attend,
        absence_deduction_fen=absence_deduction,
        late_deduction_fen=late_deduction,
        social_insurance_fen=social_insurance,
        housing_fund_fen=housing_fund,
        tax_fen=tax_fen,
    )

    return {
        "employee_id": employee["employee_id"],
        "employee_name": employee.get("name", ""),
        "role": employee.get("role", ""),
        "month": month,
        "work_days_in_month": work_days,
        "attendance_days": attendance,
        "absence_days": absence,
        "late_count": late_count,
        "early_leave_count": early_leave,
        "items": {
            "base_salary_fen": base_salary,
            "position_allowance_fen": position_allowance,
            "meal_allowance_fen": meal_allowance,
            "transport_allowance_fen": transport_allowance,
            "performance_bonus_fen": perf_bonus,
            "overtime_pay_fen": overtime_pay,
            "seniority_subsidy_fen": seniority_sub,
            "full_attendance_bonus_fen": full_attend,
            "absence_deduction_fen": absence_deduction,
            "late_deduction_fen": late_deduction,
            "social_insurance_fen": social_insurance,
            "housing_fund_fen": housing_fund,
            "tax_fen": tax_fen,
        },
        **summary,
    }


# ── 端点 ──


@router.post("/payslips/generate")
async def generate_payslips(req: GeneratePayslipsReq):
    """批量生成工资条。

    调用 salary_item_library + payroll_engine 为每位员工计算薪资明细。
    """
    if not req.employees:
        raise HTTPException(status_code=400, detail="employees list is empty")

    # 校验月份格式
    try:
        year, mon = int(req.month.split("-")[0]), int(req.month.split("-")[1])
        if mon < 1 or mon > 12:
            raise ValueError
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid month format: {req.month}") from exc

    payslips = []
    errors = []
    for emp in req.employees:
        if "employee_id" not in emp:
            errors.append({"error": "missing employee_id", "data": emp})
            continue
        try:
            slip = _build_payslip(emp, req.month)
            slip["store_id"] = req.store_id
            payslips.append(slip)
        except (KeyError, TypeError, ZeroDivisionError) as e:
            errors.append({"employee_id": emp.get("employee_id"), "error": str(e)})

    # 存储
    store_key = f"{req.store_id}:{req.month}"
    _payslip_store[store_key] = payslips

    return {
        "ok": True,
        "data": {
            "store_id": req.store_id,
            "month": req.month,
            "generated": len(payslips),
            "errors": errors,
            "payslips": payslips,
        },
    }


@router.get("/payslips")
async def list_payslips(
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """查询工资条列表。"""
    store_key = f"{store_id}:{month}"
    all_slips = _payslip_store.get(store_key, [])
    total = len(all_slips)
    start = (page - 1) * size
    end = start + size
    items = all_slips[start:end]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/payslips/{employee_id}")
async def get_employee_payslip(
    employee_id: str,
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
):
    """查询员工个人工资条。"""
    store_key = f"{store_id}:{month}"
    slips = _payslip_store.get(store_key, [])
    for slip in slips:
        if slip.get("employee_id") == employee_id:
            return {"ok": True, "data": slip}

    raise HTTPException(
        status_code=404,
        detail=f"Payslip not found for employee {employee_id} in {month}",
    )
