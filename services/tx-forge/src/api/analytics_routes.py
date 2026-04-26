from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/analytics", tags=["analytics"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.get("/stats")
async def marketplace_stats(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    row = await db.execute(
        text("""SELECT
                (SELECT COUNT(*) FROM forge.apps WHERE tenant_id = :tid) AS total_apps,
                (SELECT COUNT(*) FROM forge.developers WHERE tenant_id = :tid) AS total_developers,
                (SELECT COUNT(*) FROM forge.installations WHERE tenant_id = :tid AND status = 'active') AS active_installations"""),
        {"tid": x_tenant_id},
    )
    return dict(row.mappings().one())


@router.get("/trending")
async def trending_apps(
    period: str = Query("7d"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    days = int(period.rstrip("d")) if period.endswith("d") else 7
    rows = await db.execute(
        text("""SELECT a.id, a.name, a.category, COUNT(i.id) AS install_count
                FROM forge.apps a LEFT JOIN forge.installations i ON a.id = i.app_id AND i.created_at >= now() - make_interval(days => :days)
                WHERE a.tenant_id = :tid GROUP BY a.id ORDER BY install_count DESC LIMIT :limit"""),
        {"tid": x_tenant_id, "days": days, "limit": limit},
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "period": period}


@router.get("/categories")
async def category_stats(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("SELECT category, COUNT(*) AS app_count FROM forge.apps WHERE tenant_id = :tid GROUP BY category ORDER BY app_count DESC"),
        {"tid": x_tenant_id},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}
