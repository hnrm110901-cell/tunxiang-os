from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..schemas.workflow_schemas import WorkflowCreate, WorkflowRunStart

router = APIRouter(prefix="/api/v1/forge/workflows", tags=["Agent编排"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST / — 创建工作流
# ---------------------------------------------------------------------------
@router.post("/")
async def create_workflow(
    body: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """创建工作流."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.workflows
                (tenant_id, workflow_name, description, creator_id,
                 steps, trigger, estimated_value_fen, status)
                VALUES (:tid, :workflow_name, :description, :creator_id,
                        :steps::jsonb, :trigger::jsonb, :estimated_value_fen, 'draft')
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "workflow_name": body.workflow_name,
            "description": body.description,
            "creator_id": body.creator_id,
            "steps": str(body.steps),
            "trigger": str(body.trigger) if body.trigger else None,
            "estimated_value_fen": body.estimated_value_fen,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET / — 工作流列表
# ---------------------------------------------------------------------------
@router.get("/")
async def list_workflows(
    status: Optional[str] = Query(None),
    creator_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """工作流列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if creator_id:
        clauses.append("creator_id = :creator_id")
        params["creator_id"] = creator_id
    where = " AND ".join(clauses)

    total_row = await db.execute(text(f"SELECT COUNT(*) FROM forge.workflows WHERE {where}"), params)
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.workflows
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /{workflow_id} — 工作流详情
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """获取工作流详情."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""SELECT * FROM forge.workflows
                WHERE tenant_id = :tid AND workflow_id = :workflow_id"""),
        {"tid": x_tenant_id, "workflow_id": workflow_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return dict(row)


# ---------------------------------------------------------------------------
# POST /{workflow_id}/run — 启动工作流运行
# ---------------------------------------------------------------------------
@router.post("/{workflow_id}/run")
async def start_workflow_run(
    workflow_id: str,
    body: WorkflowRunStart,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """启动工作流运行."""
    await _set_tenant(db, x_tenant_id)
    # 获取工作流
    wf = await db.execute(
        text("""SELECT * FROM forge.workflows
                WHERE tenant_id = :tid AND workflow_id = :workflow_id"""),
        {"tid": x_tenant_id, "workflow_id": workflow_id},
    )
    wf_row = wf.mappings().first()
    if not wf_row:
        raise HTTPException(status_code=404, detail="workflow not found")

    steps = wf_row.get("steps", [])
    steps_total = len(steps) if isinstance(steps, list) else 0

    result = await db.execute(
        text("""INSERT INTO forge.workflow_runs
                (tenant_id, workflow_id, store_id, trigger_type,
                 trigger_data, status, steps_total)
                VALUES (:tid, :workflow_id, :store_id, :trigger_type,
                        :trigger_data::jsonb, 'running', :steps_total)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "workflow_id": workflow_id,
            "store_id": body.store_id,
            "trigger_type": body.trigger_type,
            "trigger_data": str(body.trigger_data),
            "steps_total": steps_total,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /{workflow_id}/runs — 运行记录列表
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """工作流运行记录列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid", "workflow_id = :workflow_id"]
    params: Dict[str, Any] = {
        "tid": x_tenant_id,
        "workflow_id": workflow_id,
        "limit": size,
        "offset": (page - 1) * size,
    }
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)

    total_row = await db.execute(text(f"SELECT COUNT(*) FROM forge.workflow_runs WHERE {where}"), params)
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.workflow_runs
                WHERE {where}
                ORDER BY started_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /{workflow_id}/analytics — 工作流分析
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}/analytics")
async def workflow_analytics(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """工作流分析."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""SELECT
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE status = 'success') AS success_count,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                    AVG(EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000)
                        FILTER (WHERE finished_at IS NOT NULL) AS avg_execution_ms,
                    SUM(total_tokens) AS total_tokens,
                    SUM(total_cost_fen) AS total_cost_fen
                FROM forge.workflow_runs
                WHERE tenant_id = :tid AND workflow_id = :workflow_id"""),
        {"tid": x_tenant_id, "workflow_id": workflow_id},
    )
    row = result.mappings().first()
    if not row:
        return {"total_runs": 0}
    data = dict(row)
    total_runs = data.get("total_runs", 0)
    success_count = data.get("success_count", 0)
    data["success_rate"] = round(success_count / total_runs, 4) if total_runs > 0 else 0.0
    return data
