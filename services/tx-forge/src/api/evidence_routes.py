from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..schemas.evidence_schemas import EvidenceCardCreate, EvidenceCardUpdate

router = APIRouter(prefix="/api/v1/forge/evidence", tags=["证据卡片"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /cards — 创建证据卡片
# ---------------------------------------------------------------------------
@router.post("/cards")
async def create_evidence_card(
    body: EvidenceCardCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """创建证据卡片."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.evidence_cards
                (tenant_id, app_id, card_type, title, summary, evidence_data,
                 score, verified_by, verification_method, expires_at)
                VALUES (:tid, :app_id, :card_type, :title, :summary, :evidence_data::jsonb,
                        :score, :verified_by, :verification_method, :expires_at)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "card_type": body.card_type,
            "title": body.title,
            "summary": body.summary,
            "evidence_data": str(body.evidence_data),
            "score": body.score,
            "verified_by": body.verified_by,
            "verification_method": body.verification_method,
            "expires_at": body.expires_at,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /cards — 卡片列表
# ---------------------------------------------------------------------------
@router.get("/cards")
async def list_evidence_cards(
    app_id: Optional[str] = Query(None),
    card_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """证据卡片列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if app_id:
        clauses.append("app_id = :app_id")
        params["app_id"] = app_id
    if card_type:
        clauses.append("card_type = :card_type")
        params["card_type"] = card_type
    if active_only:
        clauses.append("is_active = true")
    where = " AND ".join(clauses)

    total_row = await db.execute(text(f"SELECT COUNT(*) FROM forge.evidence_cards WHERE {where}"), params)
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.evidence_cards
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /{app_id}/profile — 应用信任画像
# ---------------------------------------------------------------------------
@router.get("/{app_id}/profile")
async def app_trust_profile(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """应用信任画像 — 信任评分 + 按类型分组的卡片."""
    await _set_tenant(db, x_tenant_id)

    cards = await db.execute(
        text("""SELECT * FROM forge.evidence_cards
                WHERE tenant_id = :tid AND app_id = :app_id
                ORDER BY card_type, created_at DESC"""),
        {"tid": x_tenant_id, "app_id": app_id},
    )
    all_cards = [dict(r) for r in cards.mappings().all()]

    cards_by_type: Dict[str, List[Dict[str, Any]]] = {}
    total_cards = 0
    expired_cards = 0
    score_sum = 0.0
    scored_count = 0

    for c in all_cards:
        ct = c.get("card_type", "unknown")
        cards_by_type.setdefault(ct, []).append(c)
        total_cards += 1
        if not c.get("is_active", True):
            expired_cards += 1
        if c.get("score") is not None:
            score_sum += c["score"]
            scored_count += 1

    trust_score = round(score_sum / scored_count, 2) if scored_count > 0 else 0.0

    return {
        "app_id": app_id,
        "trust_score": trust_score,
        "cards_by_type": cards_by_type,
        "total_cards": total_cards,
        "expired_cards": expired_cards,
    }


# ---------------------------------------------------------------------------
# PUT /cards/{card_id} — 更新卡片
# ---------------------------------------------------------------------------
@router.put("/cards/{card_id}")
async def update_evidence_card(
    card_id: str,
    body: EvidenceCardUpdate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """更新证据卡片."""
    await _set_tenant(db, x_tenant_id)
    set_clauses = ["updated_at = NOW()"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "card_id": card_id}

    if body.title is not None:
        set_clauses.append("title = :title")
        params["title"] = body.title
    if body.summary is not None:
        set_clauses.append("summary = :summary")
        params["summary"] = body.summary
    if body.evidence_data is not None:
        set_clauses.append("evidence_data = :evidence_data::jsonb")
        params["evidence_data"] = str(body.evidence_data)
    if body.score is not None:
        set_clauses.append("score = :score")
        params["score"] = body.score
    if body.is_active is not None:
        set_clauses.append("is_active = :is_active")
        params["is_active"] = body.is_active

    set_sql = ", ".join(set_clauses)
    result = await db.execute(
        text(f"""UPDATE forge.evidence_cards
                SET {set_sql}
                WHERE tenant_id = :tid AND card_id = :card_id
                RETURNING *"""),
        params,
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="evidence card not found")
    return dict(row)
