from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/ai-ops", tags=["ai-ops"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.get("/agents")
async def agent_observatory(
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid"
    params: Dict[str, Any] = {"tid": x_tenant_id}
    if store_id:
        where += " AND store_id = :store_id"; params["store_id"] = store_id
    rows = await db.execute(text(f"SELECT * FROM forge.ai_agents WHERE {where} ORDER BY last_active_at DESC"), params)
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/agents/{agent_id}")
async def agent_detail(
    agent_id: UUID,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT * FROM forge.ai_agents WHERE id = :id AND tenant_id = :tid"),
        {"id": str(agent_id), "tid": x_tenant_id},
    )
    agent = row.mappings().first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    stats = await db.execute(
        text("""SELECT COUNT(*) AS total_traces, AVG(latency_ms) AS avg_latency
                FROM forge.ai_traces WHERE agent_id = :id AND tenant_id = :tid AND created_at >= now() - make_interval(days => :days)"""),
        {"id": str(agent_id), "tid": x_tenant_id, "days": days},
    )
    return {**dict(agent), "stats": dict(stats.mappings().one())}


@router.get("/traces")
async def list_traces(
    agent_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    clauses, params = ["tenant_id = :tid"], {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if agent_id:
        clauses.append("agent_id = :agent_id"); params["agent_id"] = agent_id
    if status:
        clauses.append("status = :status"); params["status"] = status
    where = " AND ".join(clauses)
    rows = await db.execute(text(f"SELECT * FROM forge.ai_traces WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params)
    return {"items": [dict(r) for r in rows.mappings().all()], "page": page, "size": size}


@router.get("/traces/{session_id}")
async def trace_detail(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT * FROM forge.ai_traces WHERE session_id = :id AND tenant_id = :tid"),
        {"id": str(session_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise HTTPException(404, "Trace not found")
    return dict(result)


@router.get("/decisions")
async def decision_feed(
    agent_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid"
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": limit}
    if agent_id:
        where += " AND agent_id = :agent_id"; params["agent_id"] = agent_id
    rows = await db.execute(text(f"SELECT * FROM forge.ai_decisions WHERE {where} ORDER BY created_at DESC LIMIT :limit"), params)
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/models")
async def model_registry(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("""SELECT model_name, COUNT(*) AS call_count, AVG(latency_ms) AS avg_latency, SUM(cost) AS total_cost
                FROM forge.ai_llm_calls WHERE tenant_id = :tid AND created_at >= now() - make_interval(days => :days)
                GROUP BY model_name ORDER BY call_count DESC"""),
        {"tid": x_tenant_id, "days": days},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/llm/cost")
async def cost_dashboard(
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query("day"),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    trunc = "day" if group_by == "day" else "week" if group_by == "week" else "month"
    rows = await db.execute(
        text(f"""SELECT date_trunc(:trunc, created_at) AS period, model_name, SUM(cost) AS total_cost, COUNT(*) AS call_count
                 FROM forge.ai_llm_calls WHERE tenant_id = :tid AND created_at >= now() - make_interval(days => :days)
                 GROUP BY period, model_name ORDER BY period DESC"""),
        {"tid": x_tenant_id, "days": days, "trunc": trunc},
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "group_by": group_by}


@router.get("/llm/latency")
async def latency_stats(
    days: int = Query(7, ge=1, le=90),
    model: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid AND created_at >= now() - make_interval(days => :days)"
    params: Dict[str, Any] = {"tid": x_tenant_id, "days": days}
    if model:
        where += " AND model_name = :model"; params["model"] = model
    row = await db.execute(
        text(f"""SELECT AVG(latency_ms) AS avg_latency, percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                        percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99, COUNT(*) AS total
                 FROM forge.ai_llm_calls WHERE {where}"""),
        params,
    )
    return dict(row.mappings().one())


@router.get("/memories")
async def memory_browser(
    agent_id: Optional[str] = Query(None),
    memory_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    clauses, params = ["tenant_id = :tid"], {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if agent_id:
        clauses.append("agent_id = :agent_id"); params["agent_id"] = agent_id
    if memory_type:
        clauses.append("memory_type = :mtype"); params["mtype"] = memory_type
    where = " AND ".join(clauses)
    rows = await db.execute(text(f"SELECT * FROM forge.ai_memories WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params)
    return {"items": [dict(r) for r in rows.mappings().all()], "page": page, "size": size}
