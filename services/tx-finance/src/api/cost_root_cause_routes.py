"""Sprint D4a — 成本根因分析 API

端点：
  POST /api/v1/finance/cost/root-cause/analyze
    入参：signal_bundle dict
    出参：分析结果（ranked_causes + remediation_actions + cache stats）
  POST /api/v1/finance/cost/root-cause/review/{id}
    入参：{action: "act_on" | "dismiss"}
  GET  /api/v1/finance/cost/root-cause/summary
    查询：?months_back=3
    出参：按店/月聚合 + prompt cache hit rate 累计
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime as datetime_cls
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.cost_root_cause_service import (
    BOMDeviation,
    CostRootCauseService,
    CostSignalBundle,
    RawMaterialPriceChange,
    WasteEvent,
    save_analysis_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/finance/cost/root-cause",
    tags=["finance-cost-root-cause"],
)


# ── 请求模型 ─────────────────────────────────────────────────────

class PriceChangeInput(BaseModel):
    ingredient_name: str
    old_price_fen: int = Field(ge=0)
    new_price_fen: int = Field(ge=0)
    change_pct: float
    supplier: Optional[str] = None


class WasteEventInput(BaseModel):
    ingredient_name: str
    quantity: float = Field(ge=0)
    unit: str = "kg"
    loss_fen: int = Field(ge=0)
    reason: str = Field(
        ...,
        description="expired / prep_waste / customer_waste / other",
    )
    recorded_at: datetime_cls


class BOMDeviationInput(BaseModel):
    dish_name: str
    ingredient_name: str
    standard_qty: float = Field(ge=0)
    actual_qty: float = Field(ge=0)
    deviation_pct: float


class AnalyzeRequest(BaseModel):
    store_id: str
    store_name: str = Field(..., max_length=200)
    analysis_month: date_cls = Field(..., description="YYYY-MM-01")
    food_cost_fen: int = Field(ge=0)
    food_cost_budget_fen: int = Field(ge=0)
    cost_overrun_pct: float = Field(
        ..., description="(actual - budget) / budget，≥0.05 触发分析"
    )
    price_changes: list[PriceChangeInput] = Field(default_factory=list)
    waste_events: list[WasteEventInput] = Field(default_factory=list)
    bom_deviations: list[BOMDeviationInput] = Field(default_factory=list)
    supplier_changes: list[dict] = Field(default_factory=list)
    analysis_type: str = Field(
        default="monthly_cost_overrun",
        description="monthly_cost_overrun / sudden_cost_spike / manual",
    )


class ReviewRequest(BaseModel):
    action: str = Field(..., description="act_on | dismiss")


# ── 端点 ─────────────────────────────────────────────────────────

@router.post("/analyze", response_model=dict)
async def analyze_cost_root_cause(
    req: AnalyzeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """调 Sonnet 4.7 分析某店某月成本超支根因。

    未超预算 5% 时直接返空结果（不持久化），避免生成无意义记录。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(req.store_id, "store_id")

    if req.analysis_type not in (
        "monthly_cost_overrun", "sudden_cost_spike", "manual"
    ):
        raise HTTPException(status_code=400, detail=f"未知 analysis_type: {req.analysis_type}")

    bundle = CostSignalBundle(
        store_id=req.store_id,
        store_name=req.store_name,
        analysis_month=req.analysis_month,
        food_cost_fen=req.food_cost_fen,
        food_cost_budget_fen=req.food_cost_budget_fen,
        cost_overrun_pct=req.cost_overrun_pct,
        price_changes=[
            RawMaterialPriceChange(
                ingredient_name=p.ingredient_name,
                old_price_fen=p.old_price_fen,
                new_price_fen=p.new_price_fen,
                change_pct=p.change_pct,
                supplier=p.supplier,
            )
            for p in req.price_changes
        ],
        waste_events=[
            WasteEvent(
                ingredient_name=w.ingredient_name,
                quantity=w.quantity,
                unit=w.unit,
                loss_fen=w.loss_fen,
                reason=w.reason,
                recorded_at=w.recorded_at,
            )
            for w in req.waste_events
        ],
        bom_deviations=[
            BOMDeviation(
                dish_name=b.dish_name,
                ingredient_name=b.ingredient_name,
                standard_qty=b.standard_qty,
                actual_qty=b.actual_qty,
                deviation_pct=b.deviation_pct,
            )
            for b in req.bom_deviations
        ],
        supplier_changes=req.supplier_changes,
    )

    service = CostRootCauseService()  # 生产 wire 时传入 sonnet_invoker
    result = await service.analyze(bundle)

    if not result.ranked_causes and req.cost_overrun_pct < 0.05:
        # 未触发阈值，不落库
        return {
            "ok": True,
            "data": {
                "analysis_id": None,
                "status": "skipped",
                "reason": "cost_overrun_pct < 5%，未触发分析",
                "sonnet_analysis": result.sonnet_analysis,
            },
        }

    try:
        analysis_id = await save_analysis_to_db(
            db,
            tenant_id=x_tenant_id,
            signal_bundle=bundle,
            result=result,
            analysis_type=req.analysis_type,
        )
    except SQLAlchemyError as exc:
        logger.exception("cost_root_cause_save_failed")
        raise HTTPException(status_code=500, detail=f"持久化失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "analysis_id": analysis_id,
            "status": "analyzed",
            "model_id": result.model_id,
            "ranked_causes": [
                {
                    "cause_type": c.cause_type,
                    "confidence": c.confidence,
                    "evidence": c.evidence,
                    "impact_fen": c.impact_fen,
                    "priority": c.priority,
                }
                for c in result.ranked_causes
            ],
            "remediation_actions": [
                {
                    "action": a.action,
                    "owner_role": a.owner_role,
                    "deadline_days": a.deadline_days,
                    "expected_savings_fen": a.expected_savings_fen,
                }
                for a in result.remediation_actions
            ],
            "sonnet_analysis": result.sonnet_analysis,
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
async def review_analysis(
    analysis_id: str,
    req: ReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """店长 review：采纳（acted_on）或标记误报（dismissed）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(analysis_id, "analysis_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    new_status_map = {"act_on": "acted_on", "dismiss": "dismissed"}
    new_status = new_status_map.get(req.action)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail=f"action 必须是 act_on 或 dismiss，收到 {req.action!r}",
        )

    try:
        result = await db.execute(text("""
            UPDATE cost_root_cause_analyses
            SET status = :new_status,
                reviewed_by = CAST(:op AS uuid),
                reviewed_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'analyzed'
              AND is_deleted = false
            RETURNING id, status
        """), {
            "id": analysis_id,
            "tenant_id": x_tenant_id,
            "op": x_operator_id,
            "new_status": new_status,
        })
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("cost_root_cause_review_failed")
        raise HTTPException(status_code=500, detail=f"状态迁移失败: {exc}") from exc

    if not row:
        raise HTTPException(
            status_code=404,
            detail="analysis 不存在或状态非 analyzed，无法 review",
        )

    return {"ok": True, "data": {"analysis_id": analysis_id, "status": row["status"]}}


@router.get("/summary", response_model=dict)
async def cost_root_cause_summary(
    months_back: int = 3,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """租户 N 月累计：按状态 + prompt cache 命中率"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if months_back < 1 or months_back > 12:
        raise HTTPException(status_code=400, detail="months_back ∈ [1, 12]")

    try:
        result = await db.execute(text("""
            SELECT
                status,
                COUNT(*)                            AS total,
                COALESCE(SUM(cache_read_tokens), 0)::bigint      AS cache_read_sum,
                COALESCE(SUM(cache_creation_tokens), 0)::bigint  AS cache_create_sum,
                COALESCE(SUM(input_tokens), 0)::bigint           AS input_sum,
                COALESCE(SUM(output_tokens), 0)::bigint          AS output_sum,
                AVG(cost_overrun_pct)               AS avg_overrun_pct
            FROM cost_root_cause_analyses
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND created_at >= CURRENT_DATE - (:months_back || ' months')::interval
            GROUP BY status
            ORDER BY status
        """), {"tenant_id": x_tenant_id, "months_back": str(months_back)})
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("cost_root_cause_summary_failed")
        raise HTTPException(status_code=500, detail=f"汇总查询失败: {exc}") from exc

    total_cache_read = sum(int(r.get("cache_read_sum") or 0) for r in rows)
    total_cache_create = sum(int(r.get("cache_create_sum") or 0) for r in rows)
    total_input = sum(int(r.get("input_sum") or 0) for r in rows)
    total_output = sum(int(r.get("output_sum") or 0) for r in rows)
    total_input_all = total_cache_read + total_cache_create + total_input
    cache_hit_rate = (
        round(total_cache_read / total_input_all, 4) if total_input_all > 0 else 0.0
    )

    for r in rows:
        if r.get("avg_overrun_pct") is not None:
            r["avg_overrun_pct"] = float(r["avg_overrun_pct"])

    return {
        "ok": True,
        "data": {
            "period": {"months_back": months_back},
            "by_status": rows,
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
