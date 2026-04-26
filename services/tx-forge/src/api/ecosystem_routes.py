from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/ecosystem", tags=["生态健康"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /compute — 计算今日生态指标
# ---------------------------------------------------------------------------
@router.post("/compute")
async def compute_metrics(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """计算今日生态健康指标."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.ecosystem_metrics
                (tenant_id, metric_date, isv_active_rate, product_quality_score,
                 install_density, outcome_conversion_rate, token_efficiency,
                 developer_nps, tthw_minutes, ecosystem_gmv_fen, composite_score)
                VALUES (:tid, CURRENT_DATE, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                ON CONFLICT (tenant_id, metric_date) DO UPDATE
                SET updated_at = NOW()
                RETURNING *"""),
        {"tid": x_tenant_id},
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /metrics — 指标历史
# ---------------------------------------------------------------------------
@router.get("/metrics")
async def get_metrics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """获取指标历史."""
    await _set_tenant(db, x_tenant_id)
    rows = await db.execute(
        text("""SELECT * FROM forge.ecosystem_metrics
                WHERE tenant_id = :tid
                  AND metric_date >= CURRENT_DATE - :days * INTERVAL '1 day'
                ORDER BY metric_date DESC"""),
        {"tid": x_tenant_id, "days": days},
    )
    return {"items": [dict(r) for r in rows.mappings().all()]}


# ---------------------------------------------------------------------------
# GET /flywheel — 飞轮状态
# ---------------------------------------------------------------------------
@router.get("/flywheel")
async def get_flywheel(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """飞轮状态 — 当前 vs 30天前 + 趋势."""
    await _set_tenant(db, x_tenant_id)

    # 最新指标
    current_row = await db.execute(
        text("""SELECT * FROM forge.ecosystem_metrics
                WHERE tenant_id = :tid
                ORDER BY metric_date DESC LIMIT 1"""),
        {"tid": x_tenant_id},
    )
    current = current_row.mappings().first()

    # 30天前指标
    prev_row = await db.execute(
        text("""SELECT * FROM forge.ecosystem_metrics
                WHERE tenant_id = :tid
                  AND metric_date <= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY metric_date DESC LIMIT 1"""),
        {"tid": x_tenant_id},
    )
    previous = prev_row.mappings().first()

    current_data = dict(current) if current else {}
    previous_data = dict(previous) if previous else {}

    # 计算趋势
    trend_fields = [
        "isv_active_rate", "product_quality_score", "install_density",
        "outcome_conversion_rate", "token_efficiency", "developer_nps",
        "tthw_minutes", "ecosystem_gmv_fen", "composite_score",
    ]
    trends: Dict[str, float] = {}
    for field in trend_fields:
        cur_val = current_data.get(field, 0) or 0
        prev_val = previous_data.get(field, 0) or 0
        if prev_val != 0:
            trends[field] = round((cur_val - prev_val) / abs(prev_val) * 100, 2)
        else:
            trends[field] = 0.0

    return {
        "current": current_data,
        "previous": previous_data,
        "trends": trends,
    }
