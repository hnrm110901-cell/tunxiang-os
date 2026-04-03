"""薪资台账双视角服务：管理端台账与员工端工资条。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


def _tid(tenant_id: UUID | str) -> str:
    return str(tenant_id)


async def _set_tenant(db: AsyncSession, tenant_id: UUID | str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": _tid(tenant_id)},
    )


def _parse_period(month: str) -> tuple[int, int]:
    parts = month.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"月份格式须为 YYYY-MM: {month!r}")
    y, m = int(parts[0]), int(parts[1])
    if not (2020 <= y <= 2099 and 1 <= m <= 12):
        raise ValueError(f"月份越界: {month!r}")
    return y, m


def _build_items_detail(row: dict[str, Any]) -> list[dict[str, Any]]:
    def fen(k: str) -> int:
        return int(row.get(k) or 0)

    specs: list[tuple[str, str, int, bool]] = [
        ("BASE", "基本工资", fen("base_salary_fen"), False),
        ("COMMISSION", "提成", fen("commission_fen"), False),
        ("OVERTIME", "加班费", fen("overtime_pay_fen"), False),
        ("BONUS", "奖金", fen("bonus_fen"), False),
        ("DEDUCTION_ATTENDANCE", "考勤扣款", fen("deductions_fen"), True),
        ("SOCIAL_PERSONAL", "五险（个人）", fen("social_insurance_fen"), True),
        ("HOUSING_PERSONAL", "公积金（个人）", fen("housing_fund_fen"), True),
    ]
    out: list[dict[str, Any]] = []
    for code, name, amount, _ in specs:
        if amount != 0:
            out.append({"item_code": code, "item_name": name, "amount_fen": amount})
    return out


def _row_to_admin_item(row: dict[str, Any]) -> dict[str, Any]:
    base = int(row.get("base_salary_fen") or 0)
    commission = int(row.get("commission_fen") or 0)
    overtime = int(row.get("overtime_pay_fen") or 0)
    bonus = int(row.get("bonus_fen") or 0)
    deductions = int(row.get("deductions_fen") or 0)
    social_p = int(row.get("social_insurance_fen") or 0)
    housing = int(row.get("housing_fund_fen") or 0)
    gross = int(row.get("gross_salary_fen") or 0)
    net = int(row.get("net_salary_fen") or 0)
    social_personal = social_p + housing
    tax_fen = max(0, gross - net - social_personal)
    return {
        "employee_id": str(row["employee_id"]),
        "emp_name": str(row.get("emp_name") or ""),
        "position": str(row.get("position") or ""),
        "base_salary_fen": base,
        "overtime_fen": overtime,
        "performance_fen": commission,
        "subsidy_fen": bonus,
        "gross_fen": gross,
        "social_personal_fen": social_personal,
        "social_company_fen": 0,
        "tax_fen": tax_fen,
        "deduction_fen": deductions,
        "net_fen": net,
        "status": str(row.get("status") or "draft"),
        "items_detail": _build_items_detail(row),
    }


async def get_admin_payroll_view(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str,
    month: str,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """管理端薪资台账视图。"""
    await _set_tenant(db, tenant_id)
    year, month_num = _parse_period(month)
    if page < 1:
        page = 1
    if size < 1:
        size = 20
    offset = (page - 1) * size
    sid = str(store_id)
    tid = _tid(tenant_id)

    count_r = await db.execute(
        text("""
            SELECT COUNT(*)::bigint AS n
            FROM payroll_records_v2 p
            INNER JOIN employees e
                ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND p.store_id = :store_id
              AND p.period_year = :year
              AND p.period_month = :month
              AND p.is_deleted = FALSE
              AND e.is_deleted = FALSE
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    total = int(count_r.scalar_one() or 0)

    sum_r = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(p.gross_salary_fen), 0)::bigint AS total_gross_fen,
                COALESCE(SUM(p.net_salary_fen), 0)::bigint AS total_net_fen,
                COALESCE(SUM(
                    GREATEST(
                        0,
                        p.gross_salary_fen - p.net_salary_fen
                        - p.social_insurance_fen - p.housing_fund_fen
                    )
                ), 0)::bigint AS total_tax_fen,
                COUNT(*) FILTER (WHERE p.status = 'draft')::bigint AS pending_count,
                COUNT(*) FILTER (WHERE p.status = 'confirmed')::bigint AS confirmed_count
            FROM payroll_records_v2 p
            INNER JOIN employees e
                ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND p.store_id = :store_id
              AND p.period_year = :year
              AND p.period_month = :month
              AND p.is_deleted = FALSE
              AND e.is_deleted = FALSE
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    agg = sum_r.mappings().one()

    rows_r = await db.execute(
        text("""
            SELECT
                p.employee_id,
                p.base_salary_fen,
                p.commission_fen,
                p.overtime_pay_fen,
                p.bonus_fen,
                p.deductions_fen,
                p.social_insurance_fen,
                p.housing_fund_fen,
                p.gross_salary_fen,
                p.net_salary_fen,
                p.status,
                e.emp_name,
                e.role AS position
            FROM payroll_records_v2 p
            INNER JOIN employees e
                ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND p.store_id = :store_id
              AND p.period_year = :year
              AND p.period_month = :month
              AND p.is_deleted = FALSE
              AND e.is_deleted = FALSE
            ORDER BY e.emp_name ASC
            LIMIT :limit OFFSET :offset
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
            "limit": size,
            "offset": offset,
        },
    )
    items = [_row_to_admin_item(dict(m)) for m in rows_r.mappings().all()]

    log.info(
        "payslip_dual.admin_view",
        tenant_id=tid,
        store_id=sid,
        month=month,
        page=page,
        size=size,
        total=total,
    )

    return {
        "items": items,
        "total": total,
        "summary": {
            "total_gross_fen": int(agg["total_gross_fen"] or 0),
            "total_net_fen": int(agg["total_net_fen"] or 0),
            "total_social_company_fen": 0,
            "total_tax_fen": int(agg["total_tax_fen"] or 0),
            "confirmed_count": int(agg["confirmed_count"] or 0),
            "pending_count": int(agg["pending_count"] or 0),
        },
    }


async def get_employee_payslip(
    db: AsyncSession,
    tenant_id: UUID | str,
    employee_id: UUID | str,
    month: str,
) -> dict[str, Any]:
    """员工端工资条视图（脱敏版）。"""
    await _set_tenant(db, tenant_id)
    year, month_num = _parse_period(month)
    eid = str(employee_id)
    tid = _tid(tenant_id)

    row_r = await db.execute(
        text("""
            SELECT
                p.period_year,
                p.period_month,
                p.base_salary_fen,
                p.commission_fen,
                p.overtime_pay_fen,
                p.bonus_fen,
                p.deductions_fen,
                p.social_insurance_fen,
                p.housing_fund_fen,
                p.gross_salary_fen,
                p.net_salary_fen,
                p.paid_at,
                e.emp_name,
                e.role AS position
            FROM payroll_records_v2 p
            INNER JOIN employees e
                ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND p.employee_id = :employee_id
              AND p.period_year = :year
              AND p.period_month = :month
              AND p.is_deleted = FALSE
              AND e.is_deleted = FALSE
        """),
        {
            "tenant_id": tid,
            "employee_id": eid,
            "year": year,
            "month": month_num,
        },
    )
    row = row_r.mappings().first()
    if not row:
        raise LookupError(f"未找到工资条: employee_id={eid}, month={month}")

    r = dict(row)

    def fen(k: str) -> int:
        return int(r.get(k) or 0)

    earnings: list[dict[str, Any]] = []
    if fen("base_salary_fen"):
        earnings.append({"item_name": "基本工资", "amount_fen": fen("base_salary_fen")})
    if fen("commission_fen"):
        earnings.append({"item_name": "提成", "amount_fen": fen("commission_fen")})
    if fen("overtime_pay_fen"):
        earnings.append({"item_name": "加班费", "amount_fen": fen("overtime_pay_fen")})
    if fen("bonus_fen"):
        earnings.append({"item_name": "奖金", "amount_fen": fen("bonus_fen")})

    deductions: list[dict[str, Any]] = []
    if fen("deductions_fen"):
        deductions.append({"item_name": "考勤扣款", "amount_fen": fen("deductions_fen")})
    if fen("social_insurance_fen"):
        deductions.append({"item_name": "五险（个人）", "amount_fen": fen("social_insurance_fen")})
    if fen("housing_fund_fen"):
        deductions.append({"item_name": "公积金（个人）", "amount_fen": fen("housing_fund_fen")})

    gross = fen("gross_salary_fen")
    net = fen("net_salary_fen")
    social_personal = fen("social_insurance_fen") + fen("housing_fund_fen")
    tax_fen = max(0, gross - net - social_personal)

    paid_at = r.get("paid_at")
    payment_date: str | None
    if paid_at is None:
        payment_date = None
    elif isinstance(paid_at, datetime):
        payment_date = paid_at.date().isoformat()
    elif isinstance(paid_at, date):
        payment_date = paid_at.isoformat()
    else:
        payment_date = str(paid_at)

    log.info(
        "payslip_dual.employee_payslip",
        tenant_id=tid,
        employee_id=eid,
        month=month,
    )

    return {
        "month": month,
        "emp_name": str(r.get("emp_name") or ""),
        "position": str(r.get("position") or ""),
        "earnings": earnings,
        "deductions": deductions,
        "gross_fen": gross,
        "social_personal_fen": social_personal,
        "tax_fen": tax_fen,
        "net_fen": net,
        "payment_date": payment_date,
    }


async def get_employee_payslip_history(
    db: AsyncSession,
    tenant_id: UUID | str,
    employee_id: UUID | str,
    months: int = 12,
) -> list[dict[str, Any]]:
    """员工端工资条历史（近 N 月趋势）。"""
    await _set_tenant(db, tenant_id)
    if months < 1:
        months = 12
    eid = str(employee_id)
    tid = _tid(tenant_id)

    hist_r = await db.execute(
        text("""
            SELECT
                p.period_year,
                p.period_month,
                p.gross_salary_fen,
                p.net_salary_fen,
                p.status
            FROM payroll_records_v2 p
            WHERE p.tenant_id = :tenant_id
              AND p.employee_id = :employee_id
              AND p.is_deleted = FALSE
            ORDER BY p.period_year DESC, p.period_month DESC
            LIMIT :limit
        """),
        {"tenant_id": tid, "employee_id": eid, "limit": months},
    )
    out: list[dict[str, Any]] = []
    for m in hist_r.mappings().all():
        d = dict(m)
        y, mo = int(d["period_year"]), int(d["period_month"])
        out.append(
            {
                "month": f"{y}-{mo:02d}",
                "gross_fen": int(d.get("gross_salary_fen") or 0),
                "net_fen": int(d.get("net_salary_fen") or 0),
                "status": str(d.get("status") or ""),
            }
        )
    log.info(
        "payslip_dual.employee_history",
        tenant_id=tid,
        employee_id=eid,
        months=months,
        returned=len(out),
    )
    return out


async def confirm_payroll_batch(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str,
    month: str,
) -> dict[str, Any]:
    """批量确认薪资。"""
    await _set_tenant(db, tenant_id)
    year, month_num = _parse_period(month)
    tid = _tid(tenant_id)
    sid = str(store_id)
    result = await db.execute(
        text("""
            UPDATE payroll_records_v2
            SET status = 'confirmed',
                confirmed_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND period_year = :year
              AND period_month = :month
              AND status = 'draft'
              AND is_deleted = FALSE
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    n = int(result.rowcount or 0)
    log.info(
        "payslip_dual.confirm_batch",
        tenant_id=tid,
        store_id=sid,
        month=month,
        confirmed_count=n,
    )
    return {"confirmed_count": n}


async def mark_paid_batch(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str,
    month: str,
) -> dict[str, Any]:
    """批量标记已发放。"""
    await _set_tenant(db, tenant_id)
    year, month_num = _parse_period(month)
    tid = _tid(tenant_id)
    sid = str(store_id)
    result = await db.execute(
        text("""
            UPDATE payroll_records_v2
            SET status = 'paid',
                paid_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND period_year = :year
              AND period_month = :month
              AND status = 'confirmed'
              AND is_deleted = FALSE
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    n = int(result.rowcount or 0)
    log.info(
        "payslip_dual.mark_paid_batch",
        tenant_id=tid,
        store_id=sid,
        month=month,
        paid_count=n,
    )
    return {"paid_count": n}


async def export_payroll_summary(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str,
    month: str,
) -> dict[str, Any]:
    """导出薪资汇总数据（为 Excel 导出准备数据）。"""
    await _set_tenant(db, tenant_id)
    year, month_num = _parse_period(month)
    tid = _tid(tenant_id)
    sid = str(store_id)

    rows_r = await db.execute(
        text("""
            SELECT
                e.emp_name,
                e.role AS position,
                p.base_salary_fen,
                p.commission_fen,
                p.overtime_pay_fen,
                p.bonus_fen,
                p.deductions_fen,
                p.social_insurance_fen,
                p.housing_fund_fen,
                p.gross_salary_fen,
                p.net_salary_fen,
                p.status
            FROM payroll_records_v2 p
            INNER JOIN employees e
                ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tenant_id
              AND p.store_id = :store_id
              AND p.period_year = :year
              AND p.period_month = :month
              AND p.is_deleted = FALSE
              AND e.is_deleted = FALSE
            ORDER BY e.emp_name ASC
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    headers = [
        "姓名",
        "岗位",
        "基本工资(分)",
        "提成(分)",
        "加班费(分)",
        "奖金(分)",
        "考勤扣款(分)",
        "五险个人(分)",
        "公积金个人(分)",
        "应发(分)",
        "实发(分)",
        "状态",
    ]
    data_rows: list[list[Any]] = []
    for m in rows_r.mappings().all():
        d = dict(m)
        base = int(d.get("base_salary_fen") or 0)
        comm = int(d.get("commission_fen") or 0)
        ot = int(d.get("overtime_pay_fen") or 0)
        bonus = int(d.get("bonus_fen") or 0)
        ded = int(d.get("deductions_fen") or 0)
        sip = int(d.get("social_insurance_fen") or 0)
        hf = int(d.get("housing_fund_fen") or 0)
        gross = int(d.get("gross_salary_fen") or 0)
        net = int(d.get("net_salary_fen") or 0)
        data_rows.append(
            [
                str(d.get("emp_name") or ""),
                str(d.get("position") or ""),
                base,
                comm,
                ot,
                bonus,
                ded,
                sip,
                hf,
                gross,
                net,
                str(d.get("status") or ""),
            ]
        )

    log.info(
        "payslip_dual.export_summary",
        tenant_id=tid,
        store_id=sid,
        month=month,
        row_count=len(data_rows),
    )

    return {
        "period": f"{year}-{month_num:02d}",
        "headers": headers,
        "rows": data_rows,
    }
