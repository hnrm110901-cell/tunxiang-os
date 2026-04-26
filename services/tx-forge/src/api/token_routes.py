from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.token_schemas import TokenPricing, TokenUsageRecord

router = APIRouter(prefix="/api/v1/forge/tokens", tags=["Token计量"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /usage — 记录Token使用
# ---------------------------------------------------------------------------
@router.post("/usage")
async def record_token_usage(
    body: TokenUsageRecord,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """记录Token使用."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.token_usage
                (tenant_id, app_id, input_tokens, output_tokens, cost_fen)
                VALUES (:tid, :app_id, :input_tokens, :output_tokens, :cost_fen)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "input_tokens": body.input_tokens,
            "output_tokens": body.output_tokens,
            "cost_fen": body.cost_fen,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /usage — 查询使用量
# ---------------------------------------------------------------------------
@router.get("/usage")
async def get_token_usage(
    app_id: str = Query(...),
    period_type: Optional[str] = Query(None, description="daily/weekly/monthly"),
    period_key: Optional[str] = Query(None, description="e.g. 2026-04-25 or 2026-W17"),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """查询Token使用量."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tu.tenant_id = :tid", "tu.app_id = :app_id"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "app_id": app_id}

    if period_type and period_key:
        if period_type == "daily":
            clauses.append("DATE(tu.created_at) = :period_key::date")
        elif period_type == "monthly":
            clauses.append("TO_CHAR(tu.created_at, 'YYYY-MM') = :period_key")
        params["period_key"] = period_key

    where = " AND ".join(clauses)
    row = await db.execute(
        text(f"""SELECT
                    :app_id AS app_id,
                    COALESCE(:period_type, 'all') AS period_type,
                    COALESCE(:period_key, 'all') AS period_key,
                    COALESCE(SUM(tu.input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(tu.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(tu.input_tokens + tu.output_tokens), 0) AS total_tokens,
                    COALESCE(SUM(tu.cost_fen), 0) AS cost_fen
                FROM forge.token_usage tu
                WHERE {where}"""),
        {**params, "period_type": period_type or "all", "period_key": period_key or "all"},
    )
    data = dict(row.mappings().one())

    # Fetch budget info
    budget_row = await db.execute(
        text("""SELECT budget_fen FROM forge.token_budgets
                WHERE tenant_id = :tid AND app_id = :app_id
                LIMIT 1"""),
        {"tid": x_tenant_id, "app_id": app_id},
    )
    b = budget_row.mappings().first()
    budget_fen = dict(b)["budget_fen"] if b else 0
    data["budget_fen"] = budget_fen
    data["usage_pct"] = round(data["cost_fen"] / budget_fen * 100, 2) if budget_fen > 0 else 0.0
    return data


# ---------------------------------------------------------------------------
# GET /trend — 使用趋势
# ---------------------------------------------------------------------------
@router.get("/trend")
async def token_usage_trend(
    app_id: str = Query(...),
    days: int = Query(30),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> List[Dict[str, Any]]:
    """Token使用趋势."""
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("""SELECT DATE(created_at) AS day,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(input_tokens + output_tokens) AS total_tokens,
                    SUM(cost_fen) AS cost_fen
                FROM forge.token_usage
                WHERE tenant_id = :tid AND app_id = :app_id
                  AND created_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY DATE(created_at) ORDER BY day"""),
        {"tid": x_tenant_id, "app_id": app_id, "days": days},
    )
    return [dict(r) for r in rows.mappings().all()]


# ---------------------------------------------------------------------------
# PUT /pricing — 设置Token定价
# ---------------------------------------------------------------------------
@router.put("/pricing")
async def set_token_pricing(
    body: TokenPricing,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """设置Token定价."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.token_pricing
                (tenant_id, app_id, input_price_per_1k_fen, output_price_per_1k_fen, markup_rate)
                VALUES (:tid, :app_id, :input_price, :output_price, :markup_rate)
                ON CONFLICT (tenant_id, app_id) DO UPDATE SET
                    input_price_per_1k_fen = EXCLUDED.input_price_per_1k_fen,
                    output_price_per_1k_fen = EXCLUDED.output_price_per_1k_fen,
                    markup_rate = EXCLUDED.markup_rate,
                    updated_at = NOW()
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "input_price": body.input_price_per_1k_fen,
            "output_price": body.output_price_per_1k_fen,
            "markup_rate": body.markup_rate,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /alerts — 预算预警列表
# ---------------------------------------------------------------------------
@router.get("/alerts")
async def list_token_alerts(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> List[Dict[str, Any]]:
    """预算预警列表."""
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("""SELECT ta.app_id, ta.period_key, ta.total_tokens,
                    ta.budget_fen, ta.usage_pct, ta.alert_threshold
                FROM forge.token_alerts ta
                WHERE ta.tenant_id = :tid AND ta.resolved = false
                ORDER BY ta.usage_pct DESC"""),
        {"tid": x_tenant_id},
    )
    return [dict(r) for r in rows.mappings().all()]
