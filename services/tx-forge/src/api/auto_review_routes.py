from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.auto_review_schemas import AutoReviewRequest

router = APIRouter(prefix="/api/v1/forge/auto-review", tags=["AI审核"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /run — 执行AI自动审核
# ---------------------------------------------------------------------------
@router.post("/run")
async def run_auto_review(
    body: AutoReviewRequest,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """执行AI自动审核."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.auto_reviews
                (tenant_id, app_id, app_version_id, status)
                VALUES (:tid, :app_id, :app_version_id, 'running')
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "app_version_id": body.app_version_id,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /{review_id} — 审核结果
# ---------------------------------------------------------------------------
@router.get("/{review_id}")
async def get_auto_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """获取审核结果."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""SELECT * FROM forge.auto_reviews
                WHERE tenant_id = :tid AND review_id = :review_id"""),
        {"tid": x_tenant_id, "review_id": review_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="auto review not found")
    return dict(row)


# ---------------------------------------------------------------------------
# GET / — 审核列表
# ---------------------------------------------------------------------------
@router.get("/")
async def list_auto_reviews(
    app_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """审核列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if app_id:
        clauses.append("app_id = :app_id")
        params["app_id"] = app_id
    where = " AND ".join(clauses)

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM forge.auto_reviews WHERE {where}"), params
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.auto_reviews
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /templates — 审核模板列表
# ---------------------------------------------------------------------------
@router.get("/templates")
async def list_review_templates(
    app_category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """审核模板列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["is_active = true"]
    params: Dict[str, Any] = {}
    if app_category:
        clauses.append("app_category = :app_category")
        params["app_category"] = app_category
    where = " AND ".join(clauses)

    rows = await db.execute(
        text(f"""SELECT * FROM forge.review_templates
                WHERE {where}
                ORDER BY template_name"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}
