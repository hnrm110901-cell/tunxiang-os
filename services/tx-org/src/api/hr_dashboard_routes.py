"""人力中枢首页 API 路由

端点列表：
  GET /api/v1/hr/dashboard   人力中枢首页聚合数据

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/hr/dashboard", tags=["hr-dashboard"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/")
async def hr_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人力中枢首页聚合数据。

    包含：在职总人数、今日应到/实到/缺岗、待处理请假数、排班冲突数、
    合规预警数(open)、待审核薪资单数、人工成本率(本月)、近7天出勤率趋势、
    Agent最新建议摘要。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 1. 在职总人数
    headcount_q = text("""
        SELECT COUNT(*) AS total
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
    """)

    # 2. 今日应到/实到/缺岗
    today_q = text("""
        SELECT
            COUNT(*) AS expected,
            COUNT(CASE WHEN da.status IN ('normal', 'late', 'early_leave') THEN 1 END) AS present,
            COUNT(CASE WHEN da.status = 'absent' THEN 1 END) AS absent
        FROM daily_attendance da
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND da.date = CURRENT_DATE
          AND COALESCE(da.is_deleted, false) = false
    """)

    # 3. 待处理请假数
    leave_q = text("""
        SELECT COUNT(*) AS pending_leave
        FROM leave_requests lr
        WHERE lr.tenant_id = CAST(:tenant_id AS uuid)
          AND lr.status = 'pending'
          AND COALESCE(lr.is_deleted, false) = false
    """)

    # 4. 排班冲突数
    conflict_q = text("""
        SELECT COUNT(*) AS conflicts
        FROM schedule_conflicts sc
        WHERE sc.tenant_id = CAST(:tenant_id AS uuid)
          AND sc.status = 'open'
          AND COALESCE(sc.is_deleted, false) = false
    """)

    # 5. 合规预警数（open）
    alert_q = text("""
        SELECT COUNT(*) AS open_alerts
        FROM compliance_alerts ca
        WHERE ca.tenant_id = CAST(:tenant_id AS uuid)
          AND ca.status = 'open'
    """)

    # 6. 待审核薪资单数
    payroll_q = text("""
        SELECT COUNT(*) AS pending_payroll
        FROM payroll_records pr
        WHERE pr.tenant_id = CAST(:tenant_id AS uuid)
          AND pr.status = 'pending_review'
          AND COALESCE(pr.is_deleted, false) = false
    """)

    # 7. 近7天出勤率趋势
    trend_q = text("""
        SELECT
            da.date,
            COUNT(CASE WHEN da.status = 'normal' THEN 1 END)::float
              / GREATEST(COUNT(*), 1) AS rate
        FROM daily_attendance da
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND da.date >= CURRENT_DATE - 7
          AND COALESCE(da.is_deleted, false) = false
        GROUP BY da.date
        ORDER BY da.date
    """)

    # 8. Agent最新建议摘要
    agent_q = text("""
        SELECT agent_id, decision_type, reasoning, confidence, created_at
        FROM agent_decision_logs
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY created_at DESC
        LIMIT 5
    """)

    params = {"tenant_id": tenant_id}

    # 执行查询
    total_headcount = 0
    try:
        r = await db.execute(headcount_q, params)
        row = r.mappings().first()
        total_headcount = int(row["total"]) if row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_headcount_failed", error=str(exc))

    expected = 0
    present = 0
    absent = 0
    try:
        r = await db.execute(today_q, params)
        row = r.mappings().first()
        if row:
            expected = int(row["expected"])
            present = int(row["present"])
            absent = int(row["absent"])
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_today_failed", error=str(exc))

    pending_leave = 0
    try:
        r = await db.execute(leave_q, params)
        row = r.mappings().first()
        pending_leave = int(row["pending_leave"]) if row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_leave_failed", error=str(exc))

    conflicts = 0
    try:
        r = await db.execute(conflict_q, params)
        row = r.mappings().first()
        conflicts = int(row["conflicts"]) if row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_conflicts_failed", error=str(exc))

    open_alerts = 0
    try:
        r = await db.execute(alert_q, params)
        row = r.mappings().first()
        open_alerts = int(row["open_alerts"]) if row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_alerts_failed", error=str(exc))

    pending_payroll = 0
    try:
        r = await db.execute(payroll_q, params)
        row = r.mappings().first()
        pending_payroll = int(row["pending_payroll"]) if row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_payroll_failed", error=str(exc))

    # 近7天出勤率趋势
    attendance_trend: list[dict[str, Any]] = []
    try:
        r = await db.execute(trend_q, params)
        for row in r.mappings():
            d = row["date"]
            d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
            attendance_trend.append({
                "date": d_str,
                "rate": round(float(row["rate"]) * 100, 1),
            })
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_trend_failed", error=str(exc))

    # Agent最新建议摘要
    agent_summaries: list[dict[str, Any]] = []
    try:
        r = await db.execute(agent_q, params)
        for row in r.mappings():
            ca = row["created_at"]
            ca_str = ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
            agent_summaries.append({
                "agent_id": str(row["agent_id"]),
                "decision_type": str(row["decision_type"]),
                "reasoning": str(row["reasoning"] or ""),
                "confidence": float(row["confidence"]) if row["confidence"] else 0,
                "created_at": ca_str,
            })
    except (OperationalError, ProgrammingError) as exc:
        log.warning("hr_dashboard_agent_failed", error=str(exc))

    # 人工成本率（本月）— 需薪资+营收数据，暂置0
    labor_cost_rate = 0.0

    return _ok({
        "total_headcount": total_headcount,
        "today": {
            "expected": expected,
            "present": present,
            "absent": absent,
        },
        "pending_leave": pending_leave,
        "schedule_conflicts": conflicts,
        "open_alerts": open_alerts,
        "pending_payroll": pending_payroll,
        "labor_cost_rate": labor_cost_rate,
        "attendance_trend": attendance_trend,
        "agent_summaries": agent_summaries,
    })
