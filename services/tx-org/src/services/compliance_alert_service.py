"""tx-org 合规预警扫描服务。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee

logger = structlog.get_logger(__name__)

_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

EMPLOYEES_TABLE = Employee.__tablename__


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _document_tier(days_remaining: int) -> tuple[str, Literal["critical", "high", "medium", "low"]]:
    if days_remaining < 0:
        return "expired", "critical"
    if days_remaining <= 7:
        return "urgent", "high"
    if days_remaining <= 15:
        return "warning", "medium"
    if days_remaining <= 30:
        return "notice", "low"
    return "notice", "low"


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


async def scan_expiring_documents(
    db: AsyncSession,
    tenant_id: str,
    threshold_days: int = 30,
) -> list[dict[str, Any]]:
    """扫描即将到期的证件（健康证、身份证）。"""
    await _set_tenant(db, tenant_id)
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=threshold_days)
    sql = text(f"""
        SELECT id, emp_name, health_cert_expiry, id_card_expiry
        FROM {EMPLOYEES_TABLE}
        WHERE tenant_id = CAST(:tid AS uuid)
          AND is_deleted = FALSE
          AND (
            (health_cert_expiry IS NOT NULL AND health_cert_expiry <= :horizon)
            OR (id_card_expiry IS NOT NULL AND id_card_expiry <= :horizon)
          )
    """)
    result = await db.execute(sql, {"horizon": horizon, "tid": tenant_id})
    rows = result.mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        eid = row["id"]
        name = row["emp_name"]
        for doc_col, doc_type in (
            ("health_cert_expiry", "health_cert"),
            ("id_card_expiry", "id_card"),
        ):
            exp = row[doc_col]
            if exp is None:
                continue
            if isinstance(exp, datetime):
                exp_d = exp.date()
            else:
                exp_d = exp
            if exp_d > horizon:
                continue
            days_remaining = (exp_d - today).days
            _, severity = _document_tier(days_remaining)
            out.append(
                {
                    "employee_id": str(eid),
                    "emp_name": name,
                    "document_type": doc_type,
                    "expiry_date": exp_d.isoformat(),
                    "days_remaining": days_remaining,
                    "severity": severity,
                },
            )
    out.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x["expiry_date"]))
    logger.info(
        "compliance.scan_expiring_documents",
        tenant_id=tenant_id,
        count=len(out),
        threshold_days=threshold_days,
    )
    return out


async def scan_low_performers(
    db: AsyncSession,
    tenant_id: str,
    consecutive_months: int = 3,
) -> list[dict[str, Any]]:
    """扫描连续多个月绩效低于阈值的员工（数据来自 payroll_records_v2.performance_score）。"""
    await _set_tenant(db, tenant_id)
    ref = datetime.now(timezone.utc).date()
    sql = text(f"""
        WITH month_span AS (
            SELECT
                EXTRACT(YEAR FROM m)::int AS y,
                EXTRACT(MONTH FROM m)::int AS mo
            FROM generate_series(
                date_trunc('month', CAST(:ref_date AS date))
                    - (:n_months - 1) * interval '1 month',
                date_trunc('month', CAST(:ref_date AS date)),
                interval '1 month'
            ) AS m
        ),
        scored AS (
            SELECT
                p.employee_id,
                p.period_year,
                p.period_month,
                CAST(
                    NULLIF(BTRIM(p.performance_score::text), '') AS NUMERIC
                ) AS score
            FROM payroll_records_v2 p
            WHERE p.tenant_id = CAST(:tid AS uuid)
              AND p.is_deleted = FALSE
        )
        SELECT
            e.id AS employee_id,
            e.emp_name,
            COUNT(DISTINCT (s.period_year, s.period_month)) AS months_below,
            AVG(s.score) AS avg_score
        FROM scored s
        JOIN month_span ms
          ON ms.y = s.period_year AND ms.mo = s.period_month
        JOIN {EMPLOYEES_TABLE} e
          ON e.id = s.employee_id
         AND e.tenant_id = CAST(:tid AS uuid)
         AND e.is_deleted = FALSE
        WHERE s.score IS NOT NULL
          AND s.score < 60
        GROUP BY e.id, e.emp_name
        HAVING COUNT(DISTINCT (s.period_year, s.period_month)) = :n_months
    """)
    result = await db.execute(
        sql,
        {
            "ref_date": ref.isoformat(),
            "n_months": consecutive_months,
            "tid": tenant_id,
        },
    )
    out: list[dict[str, Any]] = []
    for row in result.mappings().all():
        avg_s = row["avg_score"]
        avg_f = float(avg_s) if avg_s is not None else 0.0
        out.append(
            {
                "employee_id": str(row["employee_id"]),
                "emp_name": row["emp_name"],
                "months_below": int(row["months_below"] or 0),
                "avg_score": round(avg_f, 2),
                "severity": "high",
            },
        )
    out.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x["employee_id"]))
    logger.info(
        "compliance.scan_low_performers",
        tenant_id=tenant_id,
        count=len(out),
        consecutive_months=consecutive_months,
    )
    return out


def _attendance_severity(absent_count: int, late_count: int) -> Literal["high", "medium"] | None:
    if absent_count >= 2:
        return "high"
    if late_count >= 5:
        return "medium"
    return None


async def _daily_attendance_late_rollup(
    db: AsyncSession,
    tenant_id: str,
    start: date,
    end: date,
) -> dict[str, dict[str, int]]:
    await _set_tenant(db, tenant_id)
    sql = text("""
        SELECT
            employee_id,
            COUNT(*) FILTER (WHERE status = 'late') AS late_count,
            COUNT(*) FILTER (WHERE status = 'early_leave') AS early_leave_count
        FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND is_deleted = FALSE
          AND date >= :start_d
          AND date < :end_d
        GROUP BY employee_id
    """)
    try:
        result = await db.execute(
            sql,
            {"start_d": start, "end_d": end, "tid": tenant_id},
        )
    except ProgrammingError:
        logger.warning(
            "compliance.scan_attendance_anomalies.daily_attendance_unavailable",
            tenant_id=tenant_id,
            start=str(start),
            end=str(end),
        )
        return {}
    m: dict[str, dict[str, int]] = {}
    for row in result.mappings().all():
        key = str(row["employee_id"])
        m[key] = {
            "late_count": int(row["late_count"] or 0),
            "early_leave_count": int(row["early_leave_count"] or 0),
        }
    return m


async def scan_attendance_anomalies(
    db: AsyncSession,
    tenant_id: str,
    month: tuple[int, int],
) -> list[dict[str, Any]]:
    """扫描指定自然月的考勤异常（旷工来自 attendance_records；迟到/早退依赖 daily_attendance 汇总）。"""
    year, mon = month
    if mon < 1 or mon > 12:
        raise ValueError("month 必须在 1–12 之间")
    start, end = _month_range(year, mon)
    await _set_tenant(db, tenant_id)
    absent_sql = text("""
        SELECT
            ar.employee_id,
            COUNT(*) FILTER (WHERE ar.absence_type = 'absent') AS absent_count
        FROM attendance_records ar
        WHERE ar.tenant_id = CAST(:tid AS uuid)
          AND ar.is_deleted = FALSE
          AND ar.work_date >= :start_d
          AND ar.work_date < :end_d
        GROUP BY ar.employee_id
    """)
    absent_result = await db.execute(
        absent_sql,
        {"start_d": start, "end_d": end, "tid": tenant_id},
    )
    absent_by_emp = {str(r["employee_id"]): int(r["absent_count"] or 0) for r in absent_result.mappings().all()}
    late_map = await _daily_attendance_late_rollup(db, tenant_id, start, end)
    emp_ids: set[str] = set(absent_by_emp.keys()) | set(late_map.keys())
    out: list[dict[str, Any]] = []
    if not emp_ids:
        logger.info(
            "compliance.scan_attendance_anomalies",
            tenant_id=tenant_id,
            month=f"{year}-{mon:02d}",
            count=0,
        )
        return out
    parsed_ids: dict[str, uuid.UUID] = {}
    for raw in emp_ids:
        try:
            parsed_ids[raw] = uuid.UUID(raw)
        except ValueError:
            logger.warning(
                "compliance.scan_attendance_anomalies.skip_invalid_employee_id",
                tenant_id=tenant_id,
                employee_id=raw,
            )
    if not parsed_ids:
        logger.info(
            "compliance.scan_attendance_anomalies",
            tenant_id=tenant_id,
            month=f"{year}-{mon:02d}",
            count=0,
        )
        return out
    await _set_tenant(db, tenant_id)
    names_sql = text(f"""
        SELECT id, emp_name
        FROM {EMPLOYEES_TABLE}
        WHERE tenant_id = CAST(:tid AS uuid)
          AND is_deleted = FALSE
          AND id IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    names_result = await db.execute(names_sql, {"ids": list(parsed_ids.values()), "tid": tenant_id})
    names = {str(r["id"]): r["emp_name"] for r in names_result.mappings().all()}
    for eid in sorted(parsed_ids.keys()):
        absent_count = absent_by_emp.get(eid, 0)
        late_info = late_map.get(eid, {"late_count": 0, "early_leave_count": 0})
        late_count = late_info["late_count"]
        early_leave_count = late_info["early_leave_count"]
        severity = _attendance_severity(absent_count, late_count)
        if severity is None:
            continue
        out.append(
            {
                "employee_id": eid,
                "emp_name": names.get(eid, ""),
                "year": year,
                "month": mon,
                "absent_count": absent_count,
                "late_count": late_count,
                "early_leave_count": early_leave_count,
                "severity": severity,
            },
        )
    out.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x["employee_id"]))
    logger.info(
        "compliance.scan_attendance_anomalies",
        tenant_id=tenant_id,
        month=f"{year}-{mon:02d}",
        count=len(out),
    )
    return out


async def scan_all(
    db: AsyncSession,
    tenant_id: str,
) -> dict[str, Any]:
    """运行证件、绩效、考勤三类扫描并汇总。"""
    today = datetime.now(timezone.utc).date()
    month_tuple = (today.year, today.month)
    documents = await scan_expiring_documents(db, tenant_id)
    performance = await scan_low_performers(db, tenant_id)
    attendance = await scan_attendance_anomalies(db, tenant_id, month_tuple)
    all_items: list[dict[str, Any]] = (
        [{**x, "category": "documents"} for x in documents]
        + [{**x, "category": "performance"} for x in performance]
        + [{**x, "category": "attendance"} for x in attendance]
    )
    summary = {
        "total": len(all_items),
        "critical": sum(1 for x in all_items if x["severity"] == "critical"),
        "high": sum(1 for x in all_items if x["severity"] == "high"),
        "medium": sum(1 for x in all_items if x["severity"] == "medium"),
        "low": sum(1 for x in all_items if x["severity"] == "low"),
    }
    documents.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x.get("expiry_date", "")))
    performance.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x["employee_id"]))
    attendance.sort(key=lambda x: (_SEVERITY_RANK[str(x["severity"])], x["employee_id"]))
    logger.info(
        "compliance.scan_all",
        tenant_id=tenant_id,
        summary=summary,
    )
    return {
        "documents": documents,
        "performance": performance,
        "attendance": attendance,
        "summary": summary,
    }
