from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/installations", tags=["installations"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def install_app(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.installations (tenant_id, app_id, store_id, status)
                VALUES (:tid, :app_id, :store_id, 'active') RETURNING *"""),
        {"tid": x_tenant_id, "app_id": body["app_id"], "store_id": body.get("store_id")},
    )
    await db.commit()
    return dict(result.mappings().one())


@router.delete("/{app_id}")
async def uninstall_app(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("UPDATE forge.installations SET status = 'uninstalled', updated_at = now() WHERE app_id = :id AND tenant_id = :tid AND status = 'active' RETURNING id"),
        {"id": str(app_id), "tid": x_tenant_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Installation not found")
    return {"ok": True, "app_id": str(app_id)}


@router.get("")
async def list_installed(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("SELECT * FROM forge.installations WHERE tenant_id = :tid AND status = 'active' ORDER BY created_at DESC"),
        {"tid": x_tenant_id},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/{app_id}/status")
async def installation_status(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT * FROM forge.installations WHERE app_id = :id AND tenant_id = :tid ORDER BY created_at DESC LIMIT 1"),
        {"id": str(app_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise HTTPException(404, "Installation not found")
    return dict(result)
