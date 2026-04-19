from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic", tags=["civic-dashboard"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Helper: fetch aggregated data for dashboard
# ---------------------------------------------------------------------------


async def _get_expiring_licenses_count(db: AsyncSession, tenant_id: str, store_id: Optional[str] = None) -> int:
    conditions = [
        "tenant_id = :tid",
        "is_deleted = FALSE",
        "expiry_date IS NOT NULL",
        "expiry_date <= CURRENT_DATE + 30 * INTERVAL '1 day'",
        "expiry_date >= CURRENT_DATE",
    ]
    params: Dict[str, Any] = {"tid": tenant_id}
    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id
    where = " AND ".join(conditions)
    result = await db.execute(text(f"SELECT COUNT(*) FROM civic_licenses WHERE {where}"), params)
    return result.scalar() or 0


async def _get_unresolved_alerts_count(db: AsyncSession, tenant_id: str, store_id: Optional[str] = None) -> int:
    conditions = ["tenant_id = :tid", "resolved = FALSE"]
    params: Dict[str, Any] = {"tid": tenant_id}
    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id
    where = " AND ".join(conditions)
    result = await db.execute(text(f"SELECT COUNT(*) FROM civic_kitchen_alerts WHERE {where}"), params)
    return result.scalar() or 0


async def _get_submission_summary(db: AsyncSession, tenant_id: str, store_id: Optional[str] = None) -> Dict[str, Any]:
    conditions = ["tenant_id = :tid", "created_at >= NOW() - INTERVAL '24 hours'"]
    params: Dict[str, Any] = {"tid": tenant_id}
    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id
    where = " AND ".join(conditions)
    result = await db.execute(
        text(
            f"SELECT COUNT(*) AS total, "
            f"COUNT(*) FILTER (WHERE status = 'success') AS success, "
            f"COUNT(*) FILTER (WHERE status = 'failed') AS failed "
            f"FROM civic_submissions WHERE {where}"
        ),
        params,
    )
    row = result.fetchone()
    if not row:
        return {"total": 0, "success": 0, "failed": 0}
    return {"total": row.total, "success": row.success, "failed": row.failed}


async def _get_compliance_score(db: AsyncSession, tenant_id: str, store_id: Optional[str] = None) -> Dict[str, Any]:
    conditions = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": tenant_id}
    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id
    where = " AND ".join(conditions)

    result = await db.execute(
        text(
            f"SELECT store_id, score, risk_level, updated_at FROM civic_compliance_scores WHERE {where} ORDER BY score ASC"
        ),
        params,
    )
    rows = [dict(r._mapping) for r in result]
    if not rows:
        return {"avg_score": 0, "stores": [], "risk_distribution": {}}

    avg_score = round(sum(r["score"] for r in rows) / len(rows), 2)
    risk_dist: Dict[str, int] = {}
    for r in rows:
        level = r.get("risk_level", "unknown")
        risk_dist[level] = risk_dist.get(level, 0) + 1

    return {"avg_score": avg_score, "stores": rows, "risk_distribution": risk_dist}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_dashboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """合规总看板（全品牌评分+风险分布+待办事项）"""
    await _set_tenant(db, x_tenant_id)
    try:
        compliance = await _get_compliance_score(db, x_tenant_id)
        expiring_licenses = await _get_expiring_licenses_count(db, x_tenant_id)
        unresolved_alerts = await _get_unresolved_alerts_count(db, x_tenant_id)
        submissions = await _get_submission_summary(db, x_tenant_id)

        # Expiring health certs
        hc_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM civic_health_certs
                WHERE tenant_id = :tid AND is_deleted = FALSE
                    AND expiry_date <= CURRENT_DATE + 30 * INTERVAL '1 day'
                    AND expiry_date >= CURRENT_DATE
            """),
            {"tid": x_tenant_id},
        )
        expiring_health_certs = hc_result.scalar() or 0

        # Due fire equipment
        fire_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM civic_fire_equipment
                WHERE tenant_id = :tid AND is_deleted = FALSE AND status = 'active'
                    AND (next_inspection_date IS NULL
                         OR next_inspection_date <= CURRENT_DATE + 7 * INTERVAL '1 day')
            """),
            {"tid": x_tenant_id},
        )
        due_fire_equipment = fire_result.scalar() or 0

        log.info("dashboard_fetched", avg_score=compliance["avg_score"])
        return {
            "ok": True,
            "data": {
                "compliance": compliance,
                "todos": {
                    "expiring_licenses": expiring_licenses,
                    "expiring_health_certs": expiring_health_certs,
                    "unresolved_alerts": unresolved_alerts,
                    "due_fire_equipment": due_fire_equipment,
                },
                "submissions_24h": submissions,
            },
        }
    except SQLAlchemyError as exc:
        log.error("dashboard_fetch_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/dashboard/store/{store_id}")
async def get_store_dashboard(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """单店合规详情"""
    await _set_tenant(db, x_tenant_id)
    try:
        compliance = await _get_compliance_score(db, x_tenant_id, store_id)
        expiring_licenses = await _get_expiring_licenses_count(db, x_tenant_id, store_id)
        unresolved_alerts = await _get_unresolved_alerts_count(db, x_tenant_id, store_id)
        submissions = await _get_submission_summary(db, x_tenant_id, store_id)

        # Trace completeness for today
        trace_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE origin_trace_code IS NOT NULL) AS traced
                FROM civic_inbound_records
                WHERE tenant_id = :tid AND store_id = :sid
                    AND created_at::date = CURRENT_DATE
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        trace_row = trace_result.fetchone()
        trace_total = trace_row.total if trace_row else 0
        trace_traced = trace_row.traced if trace_row else 0
        trace_pct = round((trace_traced / trace_total * 100) if trace_total > 0 else 0, 2)

        # Kitchen device online rate
        dev_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'online') AS online
                FROM civic_kitchen_devices
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        dev_row = dev_result.fetchone()
        dev_total = dev_row.total if dev_row else 0
        dev_online = dev_row.online if dev_row else 0
        online_rate = round((dev_online / dev_total * 100) if dev_total > 0 else 0, 2)

        # Env compliance (last 30 days emission)
        env_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE emission_concentration <= 2.0) AS compliant
                FROM civic_emission_records
                WHERE tenant_id = :tid AND store_id = :sid
                    AND created_at >= NOW() - INTERVAL '30 days'
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        env_row = env_result.fetchone()
        env_total = env_row.total if env_row else 0
        env_compliant = env_row.compliant if env_row else 0
        env_rate = round((env_compliant / env_total * 100) if env_total > 0 else 0, 2)

        log.info("store_dashboard_fetched", store_id=store_id)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "compliance": compliance,
                "traceability": {
                    "today_total": trace_total,
                    "today_traced": trace_traced,
                    "completeness_pct": trace_pct,
                },
                "kitchen": {
                    "total_devices": dev_total,
                    "online_devices": dev_online,
                    "online_rate_pct": online_rate,
                    "unresolved_alerts": unresolved_alerts,
                },
                "environment": {
                    "emission_compliance_pct": env_rate,
                    "emission_samples": env_total,
                },
                "licenses": {
                    "expiring_count": expiring_licenses,
                },
                "submissions_24h": submissions,
            },
        }
    except SQLAlchemyError as exc:
        log.error("store_dashboard_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/scores")
async def list_compliance_scores(
    risk_level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """合规评分排行"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": x_tenant_id}

        if risk_level:
            conditions.append("risk_level = :rl")
            params["rl"] = risk_level

        where = " AND ".join(conditions)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM civic_compliance_scores WHERE {where}"), params)
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(f"SELECT * FROM civic_compliance_scores WHERE {where} ORDER BY score ASC LIMIT :limit OFFSET :offset"),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("compliance_scores_listed", total=total)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        log.error("compliance_scores_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
