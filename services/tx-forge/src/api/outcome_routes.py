from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.outcome_schemas import (
    OutcomeDefinitionCreate,
    OutcomeDefinitionOut,
    OutcomeDashboard,
    OutcomeEventCreate,
    OutcomeEventOut,
    OutcomeVerify,
)

router = APIRouter(prefix="/api/v1/forge/outcomes", tags=["结果计价"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /definitions — 创建结果定义
# ---------------------------------------------------------------------------
@router.post("/definitions")
async def create_outcome_definition(
    body: OutcomeDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """创建结果定义."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.outcome_definitions
                (tenant_id, app_id, outcome_type, outcome_name, description,
                 measurement_method, price_fen_per_outcome, attribution_window_hours,
                 verification_method)
                VALUES (:tid, :app_id, :outcome_type, :outcome_name, :description,
                        :measurement_method, :price_fen, :window_hours, :verification_method)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "outcome_type": body.outcome_type,
            "outcome_name": body.outcome_name,
            "description": body.description,
            "measurement_method": body.measurement_method,
            "price_fen": body.price_fen_per_outcome,
            "window_hours": body.attribution_window_hours,
            "verification_method": body.verification_method,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /definitions — 结果定义列表
# ---------------------------------------------------------------------------
@router.get("/definitions")
async def list_outcome_definitions(
    app_id: Optional[str] = Query(None),
    outcome_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> List[Dict[str, Any]]:
    """结果定义列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id}
    if app_id:
        clauses.append("app_id = :app_id")
        params["app_id"] = app_id
    if outcome_type:
        clauses.append("outcome_type = :outcome_type")
        params["outcome_type"] = outcome_type
    if active_only:
        clauses.append("is_active = true")
    where = " AND ".join(clauses)
    rows = await db.execute(
        text(f"SELECT * FROM forge.outcome_definitions WHERE {where} ORDER BY created_at DESC"),
        params,
    )
    return [dict(r) for r in rows.mappings().all()]


# ---------------------------------------------------------------------------
# POST /events — 记录结果事件
# ---------------------------------------------------------------------------
@router.post("/events")
async def record_outcome_event(
    body: OutcomeEventCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """记录结果事件."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.outcome_events
                (tenant_id, outcome_id, app_id, store_id, agent_id,
                 decision_log_id, outcome_data)
                VALUES (:tid, :outcome_id, :app_id, :store_id, :agent_id,
                        :decision_log_id, :outcome_data::jsonb)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "outcome_id": body.outcome_id,
            "app_id": body.app_id,
            "store_id": body.store_id,
            "agent_id": body.agent_id,
            "decision_log_id": body.decision_log_id,
            "outcome_data": str(body.outcome_data),
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# POST /events/{event_id}/verify — 验证结果
# ---------------------------------------------------------------------------
@router.post("/events/{event_id}/verify")
async def verify_outcome_event(
    event_id: str,
    body: OutcomeVerify,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """验证结果事件."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""UPDATE forge.outcome_events
                SET verified = :verified, verified_at = NOW(), updated_at = NOW()
                WHERE tenant_id = :tid AND id = :event_id
                RETURNING *"""),
        {"tid": x_tenant_id, "event_id": event_id, "verified": body.verified},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="outcome event not found")
    return dict(row)


# ---------------------------------------------------------------------------
# GET /dashboard — 结果计价仪表盘
# ---------------------------------------------------------------------------
@router.get("/dashboard")
async def outcome_dashboard(
    app_id: Optional[str] = Query(None),
    days: int = Query(30),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """结果计价仪表盘."""
    await _set_tenant(db, x_tenant_id)
    app_filter = "AND oe.app_id = :app_id" if app_id else ""
    params: Dict[str, Any] = {"tid": x_tenant_id, "days": days}
    if app_id:
        params["app_id"] = app_id

    summary = await db.execute(
        text(f"""SELECT
                    COUNT(*) AS total_outcomes,
                    COUNT(*) FILTER (WHERE oe.verified = true) AS verified_outcomes,
                    COALESCE(SUM(oe.revenue_fen) FILTER (WHERE oe.verified = true), 0) AS total_revenue_fen
                FROM forge.outcome_events oe
                WHERE oe.tenant_id = :tid
                  AND oe.created_at >= NOW() - INTERVAL '1 day' * :days
                  {app_filter}"""),
        params,
    )
    s = dict(summary.mappings().one())

    by_type = await db.execute(
        text(f"""SELECT od.outcome_type, COUNT(*) AS count,
                    COALESCE(SUM(oe.revenue_fen), 0) AS revenue_fen
                FROM forge.outcome_events oe
                JOIN forge.outcome_definitions od ON od.outcome_id = oe.outcome_id
                WHERE oe.tenant_id = :tid
                  AND oe.created_at >= NOW() - INTERVAL '1 day' * :days
                  {app_filter}
                GROUP BY od.outcome_type"""),
        params,
    )

    daily = await db.execute(
        text(f"""SELECT DATE(oe.created_at) AS day, COUNT(*) AS count,
                    COALESCE(SUM(oe.revenue_fen), 0) AS revenue_fen
                FROM forge.outcome_events oe
                WHERE oe.tenant_id = :tid
                  AND oe.created_at >= NOW() - INTERVAL '1 day' * :days
                  {app_filter}
                GROUP BY DATE(oe.created_at) ORDER BY day"""),
        params,
    )

    agents = await db.execute(
        text(f"""SELECT oe.agent_id, COUNT(*) AS count,
                    COALESCE(SUM(oe.revenue_fen), 0) AS revenue_fen
                FROM forge.outcome_events oe
                WHERE oe.tenant_id = :tid AND oe.agent_id IS NOT NULL
                  AND oe.created_at >= NOW() - INTERVAL '1 day' * :days
                  {app_filter}
                GROUP BY oe.agent_id ORDER BY revenue_fen DESC LIMIT 10"""),
        params,
    )

    return {
        **s,
        "by_type": [dict(r) for r in by_type.mappings().all()],
        "daily_trend": [dict(r) for r in daily.mappings().all()],
        "top_agents": [dict(r) for r in agents.mappings().all()],
    }


# ---------------------------------------------------------------------------
# GET /events — 结果事件列表
# ---------------------------------------------------------------------------
@router.get("/events")
async def list_outcome_events(
    app_id: Optional[str] = Query(None),
    outcome_id: Optional[str] = Query(None),
    verified: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """结果事件列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if app_id:
        clauses.append("app_id = :app_id")
        params["app_id"] = app_id
    if outcome_id:
        clauses.append("outcome_id = :outcome_id")
        params["outcome_id"] = outcome_id
    if verified is not None:
        clauses.append("verified = :verified")
        params["verified"] = verified
    where = " AND ".join(clauses)

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM forge.outcome_events WHERE {where}"), params
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"SELECT * FROM forge.outcome_events WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}
