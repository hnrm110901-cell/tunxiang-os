"""工资条 API

提供工资条的批量生成、列表查询和员工个人工资条查询。
所有数据持久化到 payslip_records 表（v178 迁移）。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/org", tags=["payslips"])


# ── 辅助函数 ──


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


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
    housing_fund = int(base_salary * 0.07)  # 个人 7%

    # 个税
    gross_yuan = (
        base_salary
        + position_allowance
        + meal_allowance
        + transport_allowance
        + perf_bonus
        + overtime_pay
        + seniority_sub
        + full_attend
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

    items = {
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
    }

    meta = {
        "employee_name": employee.get("name", ""),
        "role": employee.get("role", ""),
        "work_days_in_month": work_days,
        "attendance_days": attendance,
        "absence_days": absence,
        "late_count": late_count,
        "early_leave_count": early_leave,
    }

    return {
        "employee_id": employee["employee_id"],
        "month": month,
        "items": items,
        "meta": meta,
        **summary,
    }


# ── 端点 ──


@router.post("/payslips/generate")
async def generate_payslips(
    req: GeneratePayslipsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """批量生成工资条并写入 payslip_records 表。

    调用 salary_item_library + payroll_engine 为每位员工计算薪资明细，
    逐条 INSERT 到数据库（已存在同 store_id+employee_id+pay_period 的记录会覆盖）。
    """
    tenant_id = _get_tenant_id(request)

    if not req.employees:
        raise HTTPException(status_code=400, detail="employees list is empty")

    try:
        year, mon = int(req.month.split("-")[0]), int(req.month.split("-")[1])
        if mon < 1 or mon > 12:
            raise ValueError
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid month format: {req.month}") from exc

    payslips: list[dict] = []
    errors: list[dict] = []

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

    if payslips:
        try:
            await _set_tenant(db, tenant_id)
            for slip in payslips:
                summary = slip  # summary 字段由 summarize_payroll 合并到顶层
                gross_pay_fen = summary.get("gross_pay_fen", 0)
                deductions_fen = summary.get("deductions_fen", 0)
                net_pay_fen = summary.get("net_pay_fen", 0)
                await db.execute(
                    text("""
                        INSERT INTO payslip_records
                            (tenant_id, store_id, employee_id, pay_period,
                             gross_pay_fen, deductions_fen, net_pay_fen,
                             breakdown, meta, status)
                        VALUES
                            (:tenant_id, :store_id, :employee_id, :pay_period,
                             :gross_pay_fen, :deductions_fen, :net_pay_fen,
                             :breakdown::jsonb, :meta::jsonb, 'draft')
                        ON CONFLICT DO NOTHING
                        RETURNING id
                    """),
                    {
                        "tenant_id": tenant_id,
                        "store_id": slip["store_id"],
                        "employee_id": slip["employee_id"],
                        "pay_period": slip["month"],
                        "gross_pay_fen": gross_pay_fen,
                        "deductions_fen": deductions_fen,
                        "net_pay_fen": net_pay_fen,
                        "breakdown": json.dumps(slip["items"], ensure_ascii=False),
                        "meta": json.dumps(slip["meta"], ensure_ascii=False),
                    },
                )
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail="DB error saving payslips") from exc

    return _ok(
        {
            "store_id": req.store_id,
            "month": req.month,
            "generated": len(payslips),
            "errors": errors,
            "payslips": payslips,
        }
    )


@router.get("/payslips")
async def list_payslips(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询工资条列表（分页，最多 LIMIT 50）。"""
    tenant_id = _get_tenant_id(request)
    effective_size = min(size, 50)
    offset = (page - 1) * effective_size

    try:
        await _set_tenant(db, tenant_id)
        count_row = await db.execute(
            text("""
                SELECT COUNT(*) FROM payslip_records
                WHERE tenant_id = :tenant_id::uuid
                  AND store_id   = :store_id
                  AND pay_period = :pay_period
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "pay_period": month},
        )
        total: int = count_row.scalar_one()

        rows = await db.execute(
            text("""
                SELECT id, store_id, employee_id, pay_period,
                       gross_pay_fen, deductions_fen, net_pay_fen,
                       breakdown, meta, status,
                       issued_at, acknowledged_at, created_at, updated_at
                FROM payslip_records
                WHERE tenant_id = :tenant_id::uuid
                  AND store_id   = :store_id
                  AND pay_period = :pay_period
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT  :lim
                OFFSET :off
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "pay_period": month,
                "lim": effective_size,
                "off": offset,
            },
        )
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="DB error listing payslips") from exc

    return _ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "size": effective_size,
        }
    )


@router.get("/payslips/{pid}")
async def get_payslip(
    pid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询单条工资条（按记录 UUID）。"""
    tenant_id = _get_tenant_id(request)

    try:
        await _set_tenant(db, tenant_id)
        row = await db.execute(
            text("""
                SELECT id, store_id, employee_id, pay_period,
                       gross_pay_fen, deductions_fen, net_pay_fen,
                       breakdown, meta, status,
                       issued_at, acknowledged_at, created_at, updated_at
                FROM payslip_records
                WHERE tenant_id = :tenant_id::uuid
                  AND id        = :pid::uuid
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "pid": pid},
        )
        record = row.mappings().first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="DB error fetching payslip") from exc

    if record is None:
        raise HTTPException(status_code=404, detail=f"Payslip {pid} not found")

    return _ok(dict(record))


@router.patch("/payslips/{pid}/status")
async def update_payslip_status(
    pid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新工资条状态（draft → issued → acknowledged）。

    请求体 JSON: {"status": "issued" | "acknowledged"}
    """
    tenant_id = _get_tenant_id(request)
    body = await request.json()
    new_status = body.get("status", "")
    allowed = {"issued", "acknowledged"}
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of: {', '.join(sorted(allowed))}",
        )

    extra_col = ""
    if new_status == "issued":
        extra_col = ", issued_at = NOW()"
    elif new_status == "acknowledged":
        extra_col = ", acknowledged_at = NOW()"

    try:
        await _set_tenant(db, tenant_id)
        result = await db.execute(
            text(f"""
                UPDATE payslip_records
                   SET status     = :status,
                       updated_at = NOW()
                       {extra_col}
                WHERE tenant_id  = :tenant_id::uuid
                  AND id         = :pid::uuid
                  AND is_deleted = FALSE
                RETURNING id, status, updated_at
            """),
            {"tenant_id": tenant_id, "pid": pid, "status": new_status},
        )
        updated = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="DB error updating payslip status") from exc

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Payslip {pid} not found")

    return _ok(dict(updated))
