"""流失预测评分API路由

端点：
  GET  /api/v1/predict/churn/scores          — 分页查询流失评分列表
  GET  /api/v1/predict/churn/scores/{id}     — 单个客户最新评分
  POST /api/v1/predict/churn/score/batch     — 触发批量评分
  GET  /api/v1/predict/churn/dashboard       — 流失风险大盘
  GET  /api/v1/predict/churn/interventions   — 干预记录查询
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/predict/churn", tags=["churn-prediction"])


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


async def _get_db() -> AsyncSession:  # type: ignore[misc]
    from ..database import get_session

    async for session in get_session():
        yield session


@router.get("/scores")
async def list_churn_scores(
    risk_tier: Optional[str] = Query(None),
    min_score: int = Query(0, ge=0, le=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """分页查询流失评分（最新一轮）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    where = "cs.tenant_id = :tenant_id AND cs.is_deleted = FALSE AND cs.score >= :min_score"
    params: dict[str, Any] = {"tenant_id": tenant_id, "min_score": min_score}

    if risk_tier:
        where += " AND cs.risk_tier = :risk_tier"
        params["risk_tier"] = risk_tier

    offset = (page - 1) * size
    params["size"] = size
    params["offset"] = offset

    # 只取每个客户的最新评分
    result = await db.execute(
        text(f"""
            WITH latest AS (
                SELECT customer_id, MAX(scored_at) AS latest_scored_at
                FROM churn_scores
                WHERE tenant_id = :tenant_id AND is_deleted = FALSE
                GROUP BY customer_id
            )
            SELECT cs.*
            FROM churn_scores cs
            INNER JOIN latest l ON cs.customer_id = l.customer_id AND cs.scored_at = l.latest_scored_at
            WHERE {where}
            ORDER BY cs.score DESC
            LIMIT :size OFFSET :offset
        """),
        params,
    )
    items = [dict(r) for r in result.mappings().all()]

    count_result = await db.execute(
        text(f"""
            WITH latest AS (
                SELECT customer_id, MAX(scored_at) AS latest_scored_at
                FROM churn_scores
                WHERE tenant_id = :tenant_id AND is_deleted = FALSE
                GROUP BY customer_id
            )
            SELECT COUNT(*) FROM churn_scores cs
            INNER JOIN latest l ON cs.customer_id = l.customer_id AND cs.scored_at = l.latest_scored_at
            WHERE {where}
        """),
        params,
    )
    total = count_result.scalar() or 0

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/scores/{customer_id}")
async def get_customer_churn_score(
    customer_id: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取单个客户最新流失评分"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    result = await db.execute(
        text("""
            SELECT * FROM churn_scores
            WHERE tenant_id = :tenant_id AND customer_id = :customer_id AND is_deleted = FALSE
            ORDER BY scored_at DESC
            LIMIT 1
        """),
        {"tenant_id": tenant_id, "customer_id": customer_id},
    )
    row = result.mappings().first()
    if not row:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "无评分记录"}}
    return {"ok": True, "data": dict(row)}


@router.post("/score/batch")
async def trigger_batch_scoring(
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """手动触发批量流失评分"""
    from ..services.churn_scorer import ChurnScorer

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    scorer = ChurnScorer()
    stats = await scorer.batch_score(uuid.UUID(tenant_id), db)
    await db.commit()
    return {"ok": True, "data": stats}


@router.get("/dashboard")
async def get_churn_dashboard(
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """流失风险大盘"""
    from ..services.churn_scorer import ChurnScorer

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    scorer = ChurnScorer()
    dashboard = await scorer.get_risk_dashboard(uuid.UUID(tenant_id), db)
    return {"ok": True, "data": dashboard}


@router.get("/interventions")
async def list_interventions(
    customer_id: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """查询流失干预记录"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    where = "tenant_id = :tenant_id AND is_deleted = FALSE"
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if customer_id:
        where += " AND customer_id = :customer_id"
        params["customer_id"] = customer_id
    if outcome:
        where += " AND outcome = :outcome"
        params["outcome"] = outcome

    offset = (page - 1) * size
    params["size"] = size
    params["offset"] = offset

    result = await db.execute(
        text(f"""
            SELECT * FROM churn_interventions
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :size OFFSET :offset
        """),
        params,
    )
    items = [dict(r) for r in result.mappings().all()]

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM churn_interventions WHERE {where}"),
        params,
    )
    total = count_result.scalar() or 0

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
