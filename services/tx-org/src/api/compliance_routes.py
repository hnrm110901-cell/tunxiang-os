"""合规预警 API — 证件到期 / 低绩效 / 考勤异常

数据源：
  documents   → employee_certificates（v135）
  performance → payroll_records（v031）
  attendance  → daily_attendance（v005）

前缀：/api/v1/org/compliance
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/org/compliance", tags=["compliance"])

_SCAN_TYPES = frozenset({"all", "documents", "performance", "attendance"})


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(code: str, message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


class ScanRequest(BaseModel):
    scan_type: str = Field(default="all", description="扫描范围")


# ─── RLS 辅助 ─────────────────────────────────────────────────────────────────

async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── DB 查询函数 ───────────────────────────────────────────────────────────────

async def _query_expiring_certs(
    db: AsyncSession,
    threshold_days: int,
) -> list[dict[str, Any]]:
    """从 employee_certificates 查询即将到期或已过期的证书。"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    id::text            AS document_id,
                    employee_id::text   AS employee_id,
                    cert_name           AS document_type,
                    expiry_date,
                    status,
                    (expiry_date - CURRENT_DATE) AS days_remaining
                FROM employee_certificates
                WHERE is_deleted = false
                  AND expiry_date IS NOT NULL
                  AND expiry_date <= CURRENT_DATE + :threshold * INTERVAL '1 day'
                  AND status != 'revoked'
                ORDER BY expiry_date ASC
            """),
            {"threshold": threshold_days},
        )
        rows = []
        for r in result.fetchall():
            d = dict(r._mapping)
            days = int(d["days_remaining"]) if d["days_remaining"] is not None else 0
            # 严重级别
            if days < 0:
                severity = "critical"
            elif days <= 7:
                severity = "high"
            elif days <= 14:
                severity = "medium"
            else:
                severity = "low"
            rows.append({
                "document_id": d["document_id"],
                "document_type": d["document_type"],
                "employee_id": d["employee_id"],
                "expiry_date": str(d["expiry_date"]) if d["expiry_date"] else None,
                "days_remaining": days,
                "severity": severity,
                "category": "document",
            })
        return rows
    except SQLAlchemyError:
        return []


async def _query_low_performers(
    db: AsyncSession,
    consecutive_months: int,
) -> list[dict[str, Any]]:
    """从 payroll_records 查询最近N月有薪资记录且净薪低于均值的员工（作为低绩效信号）。"""
    try:
        result = await db.execute(
            text("""
                WITH recent AS (
                    SELECT
                        employee_id,
                        COUNT(*) AS month_count,
                        AVG(net_salary) AS avg_net,
                        MIN(net_salary) AS min_net
                    FROM payroll_records
                    WHERE status != 'cancelled'
                      AND (period_year * 12 + period_month) >=
                          (EXTRACT(YEAR FROM CURRENT_DATE)::int * 12
                           + EXTRACT(MONTH FROM CURRENT_DATE)::int
                           - :months)
                    GROUP BY employee_id
                    HAVING COUNT(*) >= :months
                ),
                overall_avg AS (
                    SELECT AVG(avg_net) AS global_avg FROM recent
                )
                SELECT
                    r.employee_id::text,
                    r.month_count,
                    ROUND(r.avg_net::numeric, 2) AS avg_score,
                    oa.global_avg
                FROM recent r, overall_avg oa
                WHERE r.avg_net < oa.global_avg * 0.8
                ORDER BY r.avg_net ASC
                LIMIT 50
            """),
            {"months": consecutive_months},
        )
        rows = []
        for r in result.fetchall():
            d = dict(r._mapping)
            rows.append({
                "employee_id": d["employee_id"],
                "category": "performance",
                "severity": "high",
                "avg_score": float(d["avg_score"]),
                "consecutive_low_months": int(d["month_count"]),
            })
        return rows
    except SQLAlchemyError:
        return []


async def _query_attendance_anomalies(db: AsyncSession) -> list[dict[str, Any]]:
    """从 daily_attendance 查询近30天出勤异常（缺勤/迟到超标）员工。"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    employee_id::text,
                    COUNT(*) FILTER (WHERE is_absent = true) AS absent_days,
                    COUNT(*) FILTER (WHERE is_late = true)   AS late_days,
                    COUNT(*)                                  AS total_days
                FROM daily_attendance
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY employee_id
                HAVING
                    COUNT(*) FILTER (WHERE is_absent = true) >= 3
                    OR COUNT(*) FILTER (WHERE is_late = true) >= 5
                ORDER BY absent_days DESC, late_days DESC
                LIMIT 50
            """)
        )
        rows = []
        for r in result.fetchall():
            d = dict(r._mapping)
            absent = int(d.get("absent_days") or 0)
            late = int(d.get("late_days") or 0)
            severity = "high" if absent >= 5 else ("medium" if absent >= 3 else "low")
            rows.append({
                "employee_id": d["employee_id"],
                "category": "attendance",
                "severity": severity,
                "absent_days": absent,
                "late_days": late,
                "total_days": int(d.get("total_days") or 0),
            })
        return rows
    except SQLAlchemyError:
        return []


# ─── 合规汇总构建 ──────────────────────────────────────────────────────────────

async def _build_compliance_resp(
    db: AsyncSession,
    severity: Optional[str] = None,
    scan_type: str = "all",
) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    perf: list[dict[str, Any]] = []
    att: list[dict[str, Any]] = []

    if scan_type in ("all", "documents"):
        docs = await _query_expiring_certs(db, threshold_days=30)

    if scan_type in ("all", "performance"):
        perf = await _query_low_performers(db, consecutive_months=3)

    if scan_type in ("all", "attendance"):
        att = await _query_attendance_anomalies(db)

    # 严重级别过滤
    if severity:
        docs = [x for x in docs if x["severity"] == severity]
        perf = [x for x in perf if x["severity"] == severity]
        att = [x for x in att if x["severity"] == severity]

    all_items = docs + perf + att
    return {
        "documents": docs,
        "performance": perf,
        "attendance": att,
        "summary": {
            "total": len(all_items),
            "critical": sum(1 for x in all_items if x["severity"] == "critical"),
            "high": sum(1 for x in all_items if x["severity"] == "high"),
            "medium": sum(1 for x in all_items if x["severity"] == "medium"),
            "low": sum(1 for x in all_items if x["severity"] == "low"),
        },
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def get_compliance_alerts(
    severity: Optional[str] = Query(None, description="严重级别筛选"),
    document_type: Optional[str] = Query(None, description="证件类型筛选（暂未使用）"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询合规预警列表。"""
    await _set_rls(db, x_tenant_id)
    data = await _build_compliance_resp(db, severity=severity)
    return _ok(data)


@router.post("/scan")
async def post_compliance_scan(
    body: ScanRequest,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发合规扫描。"""
    if body.scan_type not in _SCAN_TYPES:
        return _err(
            "invalid_scan_type",
            f"scan_type 须为 {sorted(_SCAN_TYPES)} 之一",
        )
    await _set_rls(db, x_tenant_id)
    data = await _build_compliance_resp(db, scan_type=body.scan_type)
    return _ok(data)


@router.get("/documents/expiring")
async def get_expiring_compliance_documents(
    threshold_days: int = Query(30, ge=1, le=365, description="距到期天数阈值"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """返回即将到期的证件列表（来自 employee_certificates）。"""
    await _set_rls(db, x_tenant_id)
    items = await _query_expiring_certs(db, threshold_days=threshold_days)
    return _ok({
        "items": items,
        "threshold_days": threshold_days,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/performance/low")
async def get_low_performance_employees(
    consecutive_months: int = Query(3, ge=1, le=24, description="连续低绩效月数阈值"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """返回低绩效员工列表（来自 payroll_records）。"""
    await _set_rls(db, x_tenant_id)
    items = await _query_low_performers(db, consecutive_months=consecutive_months)
    return _ok({
        "items": items,
        "consecutive_months": consecutive_months,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    })
