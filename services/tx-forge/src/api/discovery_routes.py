from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.discovery_schemas import IntentSearchRequest, SearchClick

router = APIRouter(prefix="/api/v1/forge/discovery", tags=["智能发现"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /search — 意图搜索
# ---------------------------------------------------------------------------
@router.post("/search")
async def intent_search(
    body: IntentSearchRequest,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """意图搜索 — 解析自然语言查询，匹配应用和组合."""
    await _set_tenant(db, x_tenant_id)
    search_id = str(uuid4())

    # Record search log
    await db.execute(
        text("""INSERT INTO forge.search_logs
                (tenant_id, search_id, query)
                VALUES (:tid, :search_id, :query)"""),
        {"tid": x_tenant_id, "search_id": search_id, "query": body.query},
    )
    await db.commit()

    # Full-text search on apps
    apps = await db.execute(
        text("""SELECT app_id, app_name, description, category, avg_rating, install_count
                FROM forge.apps
                WHERE tenant_id = :tid AND is_deleted = false
                  AND (app_name ILIKE :q OR description ILIKE :q OR category ILIKE :q)
                ORDER BY install_count DESC LIMIT 20"""),
        {"tid": x_tenant_id, "q": f"%{body.query}%"},
    )

    # Matching combos
    combos = await db.execute(
        text("""SELECT combo_id, combo_name, description, use_case, target_role, synergy_score
                FROM forge.app_combos
                WHERE tenant_id = :tid
                  AND (combo_name ILIKE :q OR use_case ILIKE :q OR description ILIKE :q)
                ORDER BY synergy_score DESC LIMIT 10"""),
        {"tid": x_tenant_id, "q": f"%{body.query}%"},
    )

    return {
        "intents": [body.query],
        "apps": [dict(r) for r in apps.mappings().all()],
        "combos": [dict(r) for r in combos.mappings().all()],
        "search_id": search_id,
    }


# ---------------------------------------------------------------------------
# POST /search/{search_id}/click — 记录点击
# ---------------------------------------------------------------------------
@router.post("/search/{search_id}/click")
async def record_search_click(
    search_id: str,
    body: SearchClick,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """记录搜索结果点击."""
    await _set_tenant(db, x_tenant_id)
    await db.execute(
        text("""INSERT INTO forge.search_clicks
                (tenant_id, search_id, clicked_app_id)
                VALUES (:tid, :search_id, :app_id)"""),
        {"tid": x_tenant_id, "search_id": search_id, "app_id": body.clicked_app_id},
    )
    await db.commit()
    return {"ok": True, "search_id": search_id, "clicked_app_id": body.clicked_app_id}


# ---------------------------------------------------------------------------
# GET /analytics — 搜索分析
# ---------------------------------------------------------------------------
@router.get("/analytics")
async def search_analytics(
    days: int = Query(30),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """搜索分析."""
    await _set_tenant(db, x_tenant_id)
    params = {"tid": x_tenant_id, "days": days}

    total = await db.execute(
        text("""SELECT COUNT(*) AS total_searches,
                    COUNT(DISTINCT query) AS unique_queries
                FROM forge.search_logs
                WHERE tenant_id = :tid
                  AND created_at >= NOW() - INTERVAL '1 day' * :days"""),
        params,
    )

    top_queries = await db.execute(
        text("""SELECT query, COUNT(*) AS count
                FROM forge.search_logs
                WHERE tenant_id = :tid
                  AND created_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY query ORDER BY count DESC LIMIT 20"""),
        params,
    )

    click_rate = await db.execute(
        text("""SELECT
                    COUNT(DISTINCT sl.search_id) AS searches_with_clicks,
                    (SELECT COUNT(*) FROM forge.search_logs
                     WHERE tenant_id = :tid
                       AND created_at >= NOW() - INTERVAL '1 day' * :days) AS total
                FROM forge.search_clicks sl
                WHERE sl.tenant_id = :tid
                  AND sl.created_at >= NOW() - INTERVAL '1 day' * :days"""),
        params,
    )

    summary = dict(total.mappings().one())
    cr = dict(click_rate.mappings().one())
    summary["click_rate"] = round(cr["searches_with_clicks"] / cr["total"] * 100, 2) if cr["total"] > 0 else 0.0
    summary["top_queries"] = [dict(r) for r in top_queries.mappings().all()]
    return summary


# ---------------------------------------------------------------------------
# GET /combos — 组合推荐列表
# ---------------------------------------------------------------------------
@router.get("/combos")
async def list_combos(
    target_role: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """组合推荐列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if target_role:
        clauses.append("target_role = :target_role")
        params["target_role"] = target_role
    where = " AND ".join(clauses)

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM forge.app_combos WHERE {where}"), params
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.app_combos
                WHERE {where}
                ORDER BY synergy_score DESC, install_count DESC
                LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /roles/{role} — 角色推荐
# ---------------------------------------------------------------------------
@router.get("/roles/{role}")
async def role_recommendations(
    role: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """角色推荐 — 按角色返回推荐应用和组合."""
    await _set_tenant(db, x_tenant_id)
    valid_roles = {"品牌总监", "门店店长", "运营经理", "财务总监"}
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"invalid role, must be one of: {', '.join(valid_roles)}")

    apps = await db.execute(
        text("""SELECT app_id, app_name, description, category, avg_rating
                FROM forge.apps
                WHERE tenant_id = :tid AND is_deleted = false
                  AND target_roles @> ARRAY[:role]::text[]
                ORDER BY avg_rating DESC LIMIT 20"""),
        {"tid": x_tenant_id, "role": role},
    )

    combos = await db.execute(
        text("""SELECT combo_id, combo_name, description, use_case, synergy_score
                FROM forge.app_combos
                WHERE tenant_id = :tid AND target_role = :role
                ORDER BY synergy_score DESC LIMIT 10"""),
        {"tid": x_tenant_id, "role": role},
    )

    return {
        "role": role,
        "recommended_apps": [dict(r) for r in apps.mappings().all()],
        "recommended_combos": [dict(r) for r in combos.mappings().all()],
    }
