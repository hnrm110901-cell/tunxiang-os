from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/reviews", tags=["reviews"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def submit_review(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.reviews (tenant_id, app_id, reviewer_id, decision, comment)
                VALUES (:tid, :app_id, :reviewer_id, :decision, :comment) RETURNING *"""),
        {"tid": x_tenant_id, "app_id": body["app_id"], "reviewer_id": body["reviewer_id"],
         "decision": body["decision"], "comment": body.get("comment")},
    )
    if body["decision"] in ("approved", "rejected"):
        await db.execute(
            text("UPDATE forge.apps SET status = :status, updated_at = now() WHERE id = :id AND tenant_id = :tid"),
            {"status": body["decision"], "id": body["app_id"], "tid": x_tenant_id},
        )
    await db.commit()
    return dict(result.mappings().one())


@router.get("/pending")
async def list_pending(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("SELECT * FROM forge.apps WHERE status = 'pending_review' AND tenant_id = :tid ORDER BY created_at"),
        {"tid": x_tenant_id},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}


@router.get("/{app_id}/history")
async def review_history(
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
