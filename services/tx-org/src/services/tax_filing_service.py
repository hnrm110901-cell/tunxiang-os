"""薪税申报对接服务：个税申报数据生成、提交与查询（含 Mock 税局）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

TAX_FILING_STATUS: dict[str, str] = {
    "draft": "草稿",
    "generated": "已生成",
    "submitted": "已提交",
    "accepted": "已受理",
    "rejected": "被退回",
    "completed": "申报完成",
}


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


def _mask_id_card(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.strip()
    n = len(s)
    if n <= 8:
        return "****"
    return f"{s[:4]}{'*' * (n - 8)}{s[-4:]}"


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


async def generate_tax_declaration(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str,
    month: str,
) -> dict[str, Any]:
    """生成个税申报数据。"""
    await _set_tenant(db, tenant_id)
    tid = _tid(tenant_id)
    sid = str(store_id)
    year, month_num = _parse_period(month)
    month_norm = f"{year}-{month_num:02d}"

    store_r = await db.execute(
        text("""
            SELECT store_name
            FROM stores
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:store_id AS uuid)
              AND is_deleted = FALSE
            LIMIT 1
        """),
        {"tenant_id": tid, "store_id": sid},
    )
    store_row = store_r.mappings().one_or_none()
    if store_row is None:
        raise ValueError("门店不存在或无权访问")
    store_name = str(store_row["store_name"] or "")

    rows_r = await db.execute(
        text("""
            WITH ranked AS (
                SELECT
                    p.employee_id,
                    e.emp_name,
                    e.id_card_no,
                    p.period_month,
                    p.gross_salary_fen,
                    GREATEST(
                        0,
                        p.gross_salary_fen - p.net_salary_fen
                        - p.social_insurance_fen - p.housing_fund_fen
                    ) AS month_tax_fen,
                    SUM(p.gross_salary_fen) OVER (
                        PARTITION BY p.employee_id
                        ORDER BY p.period_month
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cum_gross_fen,
                    SUM(
                        GREATEST(
                            0,
                            p.gross_salary_fen - p.net_salary_fen
                            - p.social_insurance_fen - p.housing_fund_fen
                        )
                    ) OVER (
                        PARTITION BY p.employee_id
                        ORDER BY p.period_month
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cum_tax_fen
                FROM payroll_records_v2 p
                INNER JOIN employees e
                    ON e.id = p.employee_id AND e.tenant_id = p.tenant_id
                WHERE p.tenant_id = CAST(:tenant_id AS uuid)
                  AND p.store_id = CAST(:store_id AS uuid)
                  AND p.period_year = :year
                  AND p.period_month <= :month
                  AND p.is_deleted = FALSE
                  AND e.is_deleted = FALSE
            )
            SELECT
                employee_id,
                emp_name,
                id_card_no,
                gross_salary_fen,
                month_tax_fen,
                cum_gross_fen,
                cum_tax_fen
            FROM ranked
            WHERE period_month = :month
            ORDER BY emp_name ASC
        """),
        {
            "tenant_id": tid,
            "store_id": sid,
            "year": year,
            "month": month_num,
        },
    )
    rows = rows_r.mappings().all()

    employees: list[dict[str, Any]] = []
    total_tax_fen = 0
    for r in rows:
        gross = int(r["gross_salary_fen"] or 0)
        tax_fen = int(r["month_tax_fen"] or 0)
        cum_inc = int(r["cum_gross_fen"] or 0)
        cum_tax = int(r["cum_tax_fen"] or 0)
        special_fen = 0
        total_tax_fen += tax_fen
        employees.append(
            {
                "employee_id": str(r["employee_id"]),
                "emp_name": str(r.get("emp_name") or ""),
                "id_card_no_masked": _mask_id_card(
                    str(r["id_card_no"]) if r.get("id_card_no") else None
                ),
                "taxable_income_fen": gross,
                "tax_fen": tax_fen,
                "cumulative_income_fen": cum_inc,
                "cumulative_tax_fen": cum_tax,
                "special_additional_deduction_fen": special_fen,
            }
        )

    payload = {
        "month": month_norm,
        "store_name": store_name,
        "store_id": sid,
        "employees": employees,
        "status": "generated",
    }

    ins = await db.execute(
        text("""
            INSERT INTO tax_declarations (
                id, tenant_id, store_id, month, employee_count, total_tax_fen,
                declaration_data, status
            ) VALUES (
                CAST(:decl_id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:store_id AS uuid),
                :month,
                :employee_count,
                :total_tax_fen,
                CAST(:declaration_data AS jsonb),
                'generated'
            )
            RETURNING id
        """),
        {
            "decl_id": str(uuid4()),
            "tenant_id": tid,
            "store_id": sid,
            "month": month_norm,
            "employee_count": len(employees),
            "total_tax_fen": total_tax_fen,
            "declaration_data": json.dumps(payload, ensure_ascii=False),
        },
    )
    decl_id = str(ins.scalar_one())

    log.info(
        "tax_filing.generated",
        tenant_id=tid,
        store_id=sid,
        month=month_norm,
        declaration_id=decl_id,
        employee_count=len(employees),
    )

    return {
        "declaration_id": decl_id,
        "month": month_norm,
        "store_name": store_name,
        "employee_count": len(employees),
        "total_tax_fen": total_tax_fen,
        "employees": [
            {
                "employee_id": e["employee_id"],
                "emp_name": e["emp_name"],
                "id_card_no_masked": e["id_card_no_masked"],
                "taxable_income_fen": e["taxable_income_fen"],
                "tax_fen": e["tax_fen"],
                "cumulative_income_fen": e["cumulative_income_fen"],
                "cumulative_tax_fen": e["cumulative_tax_fen"],
            }
            for e in employees
        ],
        "status": "generated",
    }


async def submit_to_tax_bureau(
    db: AsyncSession,
    tenant_id: UUID | str,
    declaration_id: UUID | str,
) -> dict[str, Any]:
    """提交到自然人电子税务局（Mock）。"""
    await _set_tenant(db, tenant_id)
    tid = _tid(tenant_id)
    did = str(declaration_id)
    receipt_no = f"RCP{uuid4().hex[:16].upper()}"
    now = datetime.now(timezone.utc)

    upd = await db.execute(
        text("""
            UPDATE tax_declarations
            SET status = 'submitted',
                receipt_no = :receipt_no,
                submitted_at = :submitted_at
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:declaration_id AS uuid)
            RETURNING id
        """),
        {
            "tenant_id": tid,
            "declaration_id": did,
            "receipt_no": receipt_no,
            "submitted_at": now,
        },
    )
    row = upd.scalar_one_or_none()
    if row is None:
        raise ValueError("申报记录不存在或无权访问")

    log.info(
        "tax_filing.submitted_mock",
        tenant_id=tid,
        declaration_id=did,
        receipt_no=receipt_no,
    )

    return {
        "declaration_id": did,
        "status": "submitted",
        "receipt_no": receipt_no,
        "submitted_at": _iso_utc(now) or "",
    }


async def check_filing_status(
    db: AsyncSession,
    tenant_id: UUID | str,
    declaration_id: UUID | str,
) -> dict[str, Any]:
    """查询申报状态。"""
    await _set_tenant(db, tenant_id)
    tid = _tid(tenant_id)
    did = str(declaration_id)

    sel = await db.execute(
        text("""
            SELECT status, receipt_no, submitted_at
            FROM tax_declarations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:declaration_id AS uuid)
            LIMIT 1
        """),
        {"tenant_id": tid, "declaration_id": did},
    )
    r = sel.mappings().one_or_none()
    if r is None:
        raise ValueError("申报记录不存在或无权访问")

    return {
        "declaration_id": did,
        "status": str(r["status"] or "draft"),
        "receipt_no": r["receipt_no"],
        "submitted_at": _iso_utc(r["submitted_at"])
        if r.get("submitted_at")
        else None,
    }


async def get_filing_history(
    db: AsyncSession,
    tenant_id: UUID | str,
    store_id: UUID | str | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """查询申报历史。"""
    await _set_tenant(db, tenant_id)
    tid = _tid(tenant_id)

    cond = "d.tenant_id = CAST(:tenant_id AS uuid)"
    params: dict[str, Any] = {"tenant_id": tid}
    if store_id is not None:
        cond += " AND d.store_id = CAST(:store_id AS uuid)"
        params["store_id"] = str(store_id)
    if year is not None:
        cond += " AND d.month LIKE :year_prefix"
        params["year_prefix"] = f"{year}-%"

    q = f"""
        SELECT
            d.id AS declaration_id,
            d.month,
            s.store_name,
            d.employee_count,
            d.total_tax_fen,
            d.status,
            d.submitted_at
        FROM tax_declarations d
        INNER JOIN stores s
            ON s.id = d.store_id AND s.tenant_id = d.tenant_id
        WHERE {cond}
          AND s.is_deleted = FALSE
        ORDER BY d.month DESC, d.created_at DESC
    """
    res = await db.execute(text(q), params)
    out: list[dict[str, Any]] = []
    for m in res.mappings().all():
        out.append(
            {
                "declaration_id": str(m["declaration_id"]),
                "month": str(m["month"] or ""),
                "store_name": str(m.get("store_name") or ""),
                "employee_count": int(m["employee_count"] or 0),
                "total_tax_fen": int(m["total_tax_fen"] or 0),
                "status": str(m["status"] or "draft"),
                "submitted_at": _iso_utc(m["submitted_at"])
                if m.get("submitted_at")
                else None,
            }
        )
    return out


async def get_annual_summary(
    db: AsyncSession,
    tenant_id: UUID | str,
    employee_id: UUID | str,
    year: int,
) -> dict[str, Any]:
    """生成员工年度个税汇总（年度汇算清缴准备）。"""
    await _set_tenant(db, tenant_id)
    tid = _tid(tenant_id)
    eid = str(employee_id)

    if not (2020 <= year <= 2099):
        raise ValueError(f"年度越界: {year}")

    emp_r = await db.execute(
        text("""
            SELECT emp_name
            FROM employees
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:employee_id AS uuid)
              AND is_deleted = FALSE
            LIMIT 1
        """),
        {"tenant_id": tid, "employee_id": eid},
    )
    emp_row = emp_r.mappings().one_or_none()
    if emp_row is None:
        raise ValueError("员工不存在或无权访问")
    emp_name = str(emp_row.get("emp_name") or "")

    pr_r = await db.execute(
        text("""
            SELECT
                period_month,
                gross_salary_fen,
                net_salary_fen,
                social_insurance_fen,
                housing_fund_fen
            FROM payroll_records_v2
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND employee_id = CAST(:employee_id AS uuid)
              AND period_year = :year
              AND is_deleted = FALSE
            ORDER BY period_month ASC
        """),
        {"tenant_id": tid, "employee_id": eid, "year": year},
    )
    by_month: dict[int, dict[str, int]] = {}
    for row in pr_r.mappings().all():
        pm = int(row["period_month"])
        g = int(row["gross_salary_fen"] or 0)
        n = int(row["net_salary_fen"] or 0)
        si = int(row["social_insurance_fen"] or 0)
        hf = int(row["housing_fund_fen"] or 0)
        tax = max(0, g - n - si - hf)
        if pm in by_month:
            by_month[pm]["taxable_fen"] += g
            by_month[pm]["tax_fen"] += tax
        else:
            by_month[pm] = {"taxable_fen": g, "tax_fen": tax}

    months: list[dict[str, Any]] = []
    total_taxable = 0
    total_tax = 0
    for m in range(1, 13):
        month_key = f"{year}-{m:02d}"
        if m in by_month:
            tf = by_month[m]["taxable_fen"]
            xf = by_month[m]["tax_fen"]
        else:
            tf = 0
            xf = 0
        months.append({"month": month_key, "taxable_fen": tf, "tax_fen": xf})
        total_taxable += tf
        total_tax += xf

    avg_monthly_tax = total_tax // 12

    log.info(
        "tax_filing.annual_summary",
        tenant_id=tid,
        employee_id=eid,
        year=year,
        total_tax_fen=total_tax,
    )

    return {
        "year": year,
        "employee_id": eid,
        "emp_name": emp_name,
        "months": months,
        "total_taxable_fen": total_taxable,
        "total_tax_fen": total_tax,
        "avg_monthly_tax_fen": avg_monthly_tax,
    }
