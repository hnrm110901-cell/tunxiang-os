from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.builder_schemas import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/v1/forge/builder", tags=["Forge Builder"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /projects — 创建项目
# ---------------------------------------------------------------------------
@router.post("/projects")
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """创建低代码项目."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.builder_projects
                (tenant_id, developer_id, project_name, template_type, status)
                VALUES (:tid, :developer_id, :project_name, :template_type, 'draft')
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "developer_id": body.developer_id,
            "project_name": body.project_name,
            "template_type": body.template_type,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /projects — 项目列表
# ---------------------------------------------------------------------------
@router.get("/projects")
async def list_projects(
    developer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """项目列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if developer_id:
        clauses.append("developer_id = :developer_id")
        params["developer_id"] = developer_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM forge.builder_projects WHERE {where}"), params
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.builder_projects
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /projects/{project_id} — 项目详情
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """获取项目详情."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""SELECT * FROM forge.builder_projects
                WHERE tenant_id = :tid AND project_id = :project_id"""),
        {"tid": x_tenant_id, "project_id": project_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return dict(row)


# ---------------------------------------------------------------------------
# PUT /projects/{project_id} — 更新项目
# ---------------------------------------------------------------------------
@router.put("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """更新项目."""
    await _set_tenant(db, x_tenant_id)
    set_clauses = ["updated_at = NOW()"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "project_id": project_id}

    if body.project_name is not None:
        set_clauses.append("project_name = :project_name")
        params["project_name"] = body.project_name
    if body.canvas is not None:
        set_clauses.append("canvas = :canvas::jsonb")
        params["canvas"] = str(body.canvas)
    if body.generated_code is not None:
        set_clauses.append("generated_code = :generated_code")
        params["generated_code"] = body.generated_code
    if body.status is not None:
        set_clauses.append("status = :status")
        params["status"] = body.status

    set_sql = ", ".join(set_clauses)
    result = await db.execute(
        text(f"""UPDATE forge.builder_projects
                SET {set_sql}
                WHERE tenant_id = :tid AND project_id = :project_id
                RETURNING *"""),
        params,
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return dict(row)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/submit — 提交项目为应用
# ---------------------------------------------------------------------------
@router.post("/projects/{project_id}/submit")
async def submit_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """提交项目为应用."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""UPDATE forge.builder_projects
                SET status = 'submitted', updated_at = NOW()
                WHERE tenant_id = :tid AND project_id = :project_id AND status = 'draft'
                RETURNING *"""),
        {"tid": x_tenant_id, "project_id": project_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="project not found or not in draft status")
    return dict(row)


# ---------------------------------------------------------------------------
# GET /templates — 模板列表
# ---------------------------------------------------------------------------
@router.get("/templates")
async def list_templates(
    template_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """模板列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["1=1"]
    params: Dict[str, Any] = {}
    if template_type:
        clauses.append("template_type = :template_type")
        params["template_type"] = template_type
    where = " AND ".join(clauses)

    rows = await db.execute(
        text(f"""SELECT * FROM forge.builder_templates
                WHERE {where}
                ORDER BY usage_count DESC"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}
