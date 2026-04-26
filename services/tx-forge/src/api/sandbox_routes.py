from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/sandboxes", tags=["sandboxes"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def create_sandbox(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.sandboxes (tenant_id, app_id, developer_id, status, config)
                VALUES (:tid, :app_id, :developer_id, 'provisioning', :config::jsonb) RETURNING *"""),
        {"tid": x_tenant_id, "app_id": body["app_id"], "developer_id": body["developer_id"],
         "config": body.get("config", "{}")},
    )
    await db.commit()
    return dict(result.mappings().one())


@router.get("/{sandbox_id}")
async def get_sandbox(
    sandbox_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("SELECT * FROM forge.sandboxes WHERE id = :id AND tenant_id = :tid"),
        {"id": str(sandbox_id), "tid": x_tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise HTTPException(404, "Sandbox not found")
    return dict(result)


@router.delete("/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("UPDATE forge.sandboxes SET status = 'deleted', updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING id"),
        {"id": str(sandbox_id), "tid": x_tenant_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Sandbox not found")
    return {"ok": True, "sandbox_id": str(sandbox_id)}
