from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/developers", tags=["developers"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def register_developer(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.developers (tenant_id, name, email, company, status)
                VALUES (:tid, :name, :email, :company, 'pending')
                RETURNING id, name, email, status, created_at"""),
        {"tid": x_tenant_id, "name": body["name"], "email": body["email"], "company": body.get("company")},
    )
    await db.commit()
    row = result.mappings().one()
    return dict(row)


@router.get("")
async def list_developers(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    offset = (page - 1) * size
    where = "WHERE tenant_id = :tid" + (" AND status = :status" if status else "")
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": offset}
    if status:
        params["status"] = status
    rows = await db.execute(
        text(f"SELECT * FROM forge.developers {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "page": page, "size": size}


@router.get("/{developer_id}")
async def get_developer(
    developer_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT * FROM forge.developers WHERE id = :id AND tenant_id = :tid"),
        {"id": str(developer_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise HTTPException(404, "Developer not found")
    return dict(result)


@router.put("/{developer_id}")
async def update_developer(
    developer_id: UUID,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    sets = ", ".join(f"{k} = :{k}" for k in body)
    params = {**body, "id": str(developer_id), "tid": x_tenant_id}
    result = await db.execute(
        text(f"UPDATE forge.developers SET {sets}, updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING *"),
        params,
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Developer not found")
    return dict(row)


@router.get("/{developer_id}/revenue")
async def get_developer_revenue(
    developer_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("""SELECT developer_id, SUM(amount) AS total_revenue, COUNT(*) AS tx_count
                FROM forge.payouts WHERE developer_id = :did AND tenant_id = :tid
                GROUP BY developer_id"""),
        {"did": str(developer_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    if not result:
        return {"developer_id": str(developer_id), "total_revenue": 0, "tx_count": 0}
    return dict(result)
