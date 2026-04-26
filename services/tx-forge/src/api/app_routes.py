from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/apps", tags=["apps"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def submit_app(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.apps (tenant_id, developer_id, name, category, description, version, status)
                VALUES (:tid, :developer_id, :name, :category, :description, :version, 'draft')
                RETURNING *"""),
        {"tid": x_tenant_id, **{k: body[k] for k in ("developer_id", "name", "category", "description", "version")}},
    )
    await db.commit()
    return dict(result.mappings().one())


@router.get("")
async def list_apps(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    clauses, params = ["tenant_id = :tid"], {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if category:
        clauses.append("category = :category"); params["category"] = category
    if status:
        clauses.append("status = :status"); params["status"] = status
    if q:
        clauses.append("name ILIKE :q"); params["q"] = f"%{q}%"
    where = " AND ".join(clauses)
    rows = await db.execute(text(f"SELECT * FROM forge.apps WHERE {where} ORDER BY {sort_by} DESC LIMIT :limit OFFSET :offset"), params)
    return {"items": [dict(r) for r in rows.mappings().all()], "page": page, "size": size}


@router.get("/{app_id}")
async def get_app(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(text("SELECT * FROM forge.apps WHERE id = :id AND tenant_id = :tid"), {"id": str(app_id), "tid": x_tenant_id})
    result = row.mappings().first()
    if not result:
        raise HTTPException(404, "App not found")
    return dict(result)


@router.put("/{app_id}")
async def update_app(
    app_id: UUID,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    sets = ", ".join(f"{k} = :{k}" for k in body)
    params = {**body, "id": str(app_id), "tid": x_tenant_id}
    result = await db.execute(text(f"UPDATE forge.apps SET {sets}, updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING *"), params)
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "App not found")
    return dict(row)


@router.get("/{app_id}/revenue")
async def get_app_revenue(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT app_id, SUM(amount) AS total_revenue, COUNT(*) AS tx_count FROM forge.app_revenue WHERE app_id = :id AND tenant_id = :tid GROUP BY app_id"),
        {"id": str(app_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else {"app_id": str(app_id), "total_revenue": 0, "tx_count": 0}


@router.get("/{app_id}/reviews")
async def get_app_reviews(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("SELECT * FROM forge.reviews WHERE app_id = :id AND tenant_id = :tid ORDER BY created_at DESC"),
        {"id": str(app_id), "tid": x_tenant_id},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}
