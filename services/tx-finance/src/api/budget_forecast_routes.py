"""Sprint D4c — 预算预测 API

端点：
  POST /api/v1/finance/budget/forecast
    入参：近 N 月 P&L 历史 + 预测窗口
    出参：predicted_line_items + variance_risks + preventive_actions + cache stats
  POST /api/v1/finance/budget/forecast/review/{id}
    入参：{action: approve | revise | escalate, revision_note?}
  GET  /api/v1/finance/budget/forecast/summary
    按 status + business_type 聚合 + Prompt Cache 命中率
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.budget_forecast_service import (
    BudgetForecastService,
    BudgetSignalBundle,
    MonthlyPnL,
    save_forecast_to_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/finance/budget/forecast",
    tags=["finance-budget-forecast"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class MonthlyPnLInput(BaseModel):
    month: date_cls = Field(..., description="YYYY-MM-01")
    revenue_fen: int = Field(ge=0)
    food_cost_fen: int = Field(ge=0)
    labor_cost_fen: int = Field(ge=0)
    rent_fen: int = Field(ge=0)
    utility_fen: int = Field(ge=0)
    other_fen: int = Field(ge=0)


class ForecastRequest(BaseModel):
    forecast_month: date_cls = Field(..., description="预测期首日 YYYY-MM-01")
    forecast_scope: str = Field(
        default="monthly_store",
        description="monthly_brand|monthly_store|quarterly_brand|adhoc",
    )
    business_type: str = Field(
        default="full_service",
        description="full_service|quick_service|tea_beverage|buffet|hot_pot",
    )
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    history: list[MonthlyPnLInput] = Field(..., min_length=1)


class ReviewRequest(BaseModel):
    action: str = Field(..., description="approve|revise|escalate")
    revision_note: Optional[str] = None


# ── 端点 ────────────────────────────────────────────────────────


@router.post("", response_model=dict)
async def create_budget_forecast(
    req: ForecastRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """调 Sonnet 4.7 预测下期预算 + 标注 variance 风险"""
    tenant_uuid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    bundle = BudgetSignalBundle(
        tenant_id=str(tenant_uuid),
        forecast_month=req.forecast_month,
        forecast_scope=req.forecast_scope,
        business_type=req.business_type,
        brand_id=req.brand_id,
        brand_name=req.brand_name,
        store_id=req.store_id,
        store_name=req.store_name,
        history=[
            MonthlyPnL(
                month=h.month,
                revenue_fen=h.revenue_fen,
                food_cost_fen=h.food_cost_fen,
                labor_cost_fen=h.labor_cost_fen,
                rent_fen=h.rent_fen,
                utility_fen=h.utility_fen,
                other_fen=h.other_fen,
            )
            for h in req.history
        ],
    )

    service = BudgetForecastService()
    result = await service.forecast(bundle)

    try:
        analysis_id = await save_forecast_to_db(
            db,
            tenant_id=x_tenant_id,
            signal_bundle=bundle,
            result=result,
        )
    except SQLAlchemyError as exc:
        logger.exception("budget_forecast_save_failed")
        raise HTTPException(
            status_code=500, detail=f"持久化失败: {exc}"
        ) from exc

    status = "escalated" if result.has_critical or result.has_legal_flag else "analyzed"

    return {
        "ok": True,
        "data": {
            "analysis_id": analysis_id,
            "status": status,
            "model_id": result.model_id,
            "sonnet_analysis": result.sonnet_analysis,
            "predicted_line_items": [
                li.to_dict() for li in result.predicted_line_items
            ],
            "variance_risks": [r.to_dict() for r in result.variance_risks],
            "preventive_actions": [a.to_dict() for a in result.preventive_actions],
            "summary": {
                "predicted_revenue_fen": result.predicted_revenue_fen,
                "predicted_net_fen": result.predicted_net_fen,
                "predicted_margin_pct": result.predicted_margin_pct,
                "risk_count": len(result.variance_risks),
                "critical_count": sum(
                    1 for r in result.variance_risks if r.severity == "critical"
                ),
                "legal_flag_count": sum(
                    1 for r in result.variance_risks if r.legal_flag
                ),
            },
            "prompt_cache_stats": {
                "cache_read_tokens": result.cache_read_tokens,
                "cache_creation_tokens": result.cache_creation_tokens,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_hit_rate": result.cache_hit_rate,
            },
        },
    }


@router.post("/review/{analysis_id}", response_model=dict)
async def review_forecast(
    analysis_id: str,
    req: ReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """CFO 审核：approve / revise / escalate"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(analysis_id, "analysis_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    status_map = {
        "approve": "approved",
        "revise": "revised",
        "escalate": "escalated",
    }
    new_status = status_map.get(req.action)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail=f"action 必须是 approve|revise|escalate，收到 {req.action!r}",
        )
    if new_status == "revised" and not (req.revision_note and req.revision_note.strip()):
        raise HTTPException(
            status_code=400, detail="revise 操作必须附 revision_note"
        )

    try:
        result = await db.execute(
            text("""
                UPDATE budget_forecast_analyses
                SET status = :new_status,
                    reviewed_by = CAST(:op AS uuid),
                    reviewed_at = NOW(),
                    revision_note = COALESCE(:note, revision_note),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('analyzed', 'escalated')
                  AND is_deleted = false
                RETURNING id, status
            """),
            {
                "id": analysis_id,
                "tenant_id": x_tenant_id,
                "op": x_operator_id,
                "new_status": new_status,
                "note": req.revision_note,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("budget_forecast_review_failed")
        raise HTTPException(
            status_code=500, detail=f"状态迁移失败: {exc}"
        ) from exc

    if not row:
        raise HTTPException(
            status_code=404, detail="分析不存在或状态不允许 review"
        )

    return {
        "ok": True,
        "data": {"analysis_id": analysis_id, "status": row["status"]},
    }


@router.get("/summary", response_model=dict)
async def budget_forecast_summary(
    months_back: int = 6,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按 status + business_type 聚合 + Prompt Cache 命中率"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if months_back < 1 or months_back > 24:
        raise HTTPException(status_code=400, detail="months_back ∈ [1, 24]")

    try:
        result = await db.execute(
            text("""
                SELECT
                    status,
                    business_type,
                    COUNT(*)                                        AS total,
                    COALESCE(SUM(predicted_revenue_fen), 0)::bigint AS revenue_sum,
                    COALESCE(SUM(predicted_net_fen), 0)::bigint     AS net_sum,
                    COALESCE(AVG(predicted_margin_pct), 0)::float   AS avg_margin,
                    COALESCE(SUM(cache_read_tokens), 0)::bigint     AS cache_read_sum,
                    COALESCE(SUM(cache_creation_tokens), 0)::bigint AS cache_create_sum,
                    COALESCE(SUM(input_tokens), 0)::bigint          AS input_sum,
                    COALESCE(SUM(output_tokens), 0)::bigint         AS output_sum
                FROM budget_forecast_analyses
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                  AND created_at >= CURRENT_DATE - (:months_back || ' months')::interval
                GROUP BY status, business_type
                ORDER BY status, business_type
            """),
            {"tenant_id": x_tenant_id, "months_back": str(months_back)},
        )
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("budget_forecast_summary_failed")
        raise HTTPException(
            status_code=500, detail=f"汇总失败: {exc}"
        ) from exc

    total_cache_read = sum(int(r.get("cache_read_sum") or 0) for r in rows)
    total_cache_create = sum(int(r.get("cache_create_sum") or 0) for r in rows)
    total_input = sum(int(r.get("input_sum") or 0) for r in rows)
    total_output = sum(int(r.get("output_sum") or 0) for r in rows)
    total_input_all = total_cache_read + total_cache_create + total_input
    cache_hit_rate = (
        round(total_cache_read / total_input_all, 4) if total_input_all > 0 else 0.0
    )

    return {
        "ok": True,
        "data": {
            "period": {"months_back": months_back},
            "by_status_business_type": rows,
            "aggregate": {
                "total_forecasts": sum(int(r.get("total") or 0) for r in rows),
                "total_predicted_revenue_fen": sum(
                    int(r.get("revenue_sum") or 0) for r in rows
                ),
                "total_predicted_net_fen": sum(
                    int(r.get("net_sum") or 0) for r in rows
                ),
            },
            "prompt_cache": {
                "cache_read_tokens": total_cache_read,
                "cache_creation_tokens": total_cache_create,
                "non_cached_input_tokens": total_input,
                "output_tokens": total_output,
                "cache_hit_rate": cache_hit_rate,
                "cache_hit_target": 0.75,
                "meets_target": cache_hit_rate >= 0.75,
            },
        },
    }


# ── 辅助 ─────────────────────────────────────────────────────────


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
