from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/sdk", tags=["sdk"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("/keys")
async def generate_key(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.sdk_keys (tenant_id, developer_id, name, key_hash, status)
                VALUES (:tid, :developer_id, :name, gen_random_uuid()::text, 'active') RETURNING *"""),
        {"tid": x_tenant_id, "developer_id": body["developer_id"], "name": body.get("name", "default")},
    )
    await db.commit()
    return dict(result.mappings().one())


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text(
            "UPDATE forge.sdk_keys SET status = 'revoked', updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING id"
        ),
        {"id": str(key_id), "tid": x_tenant_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Key not found")
    return {"ok": True, "key_id": str(key_id)}


@router.get("/keys")
async def list_keys(
    developer_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid"
    params: Dict[str, Any] = {"tid": x_tenant_id}
    if developer_id:
        where += " AND developer_id = :did"
        params["did"] = developer_id
    rows = await db.execute(text(f"SELECT * FROM forge.sdk_keys WHERE {where} ORDER BY created_at DESC"), params)
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/usage")
async def usage_stats(
    developer_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid"
    params: Dict[str, Any] = {"tid": x_tenant_id}
    if developer_id:
        where += " AND developer_id = :did"
        params["did"] = developer_id
    row = await db.execute(
        text(f"SELECT COUNT(*) AS total_calls, SUM(tokens_used) AS total_tokens FROM forge.sdk_usage WHERE {where}"),
        params,
    )
    return dict(row.mappings().one())
