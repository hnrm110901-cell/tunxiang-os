"""Sprint D3c — 菜品动态定价 API

端点：
  POST /api/v1/menu/dish/pricing/suggest
    入参：{dish_id, dish_name, current_price_fen, cost_fen, observations:[{day, price_fen, qty}]}
    出参：PricingSuggestion + 落库 id
  POST /api/v1/menu/dish/pricing/confirm/{id}  → human_confirmed
  POST /api/v1/menu/dish/pricing/apply/{id}   → applied
  POST /api/v1/menu/dish/pricing/reject/{id}   → rejected
  POST /api/v1/menu/dish/pricing/revert/{id}  → reverted
  GET  /api/v1/menu/dish/pricing/summary      按 store 聚合
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

from ..services.dish_dynamic_pricing_service import (
    DishDynamicPricingService,
    PricingObservation,
    save_suggestion_to_db,
    transition_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/menu/dish/pricing",
    tags=["menu-dish-pricing"],
)


# ── 请求/响应模型 ────────────────────────────────────────────────

class ObservationInput(BaseModel):
    day: date_cls
    price_fen: int = Field(gt=0)
    quantity_sold: int = Field(ge=0)


class SuggestRequest(BaseModel):
    dish_id: str
    dish_name: str = Field(..., max_length=200)
    current_price_fen: int = Field(gt=0)
    cost_fen: int = Field(ge=0)
    current_daily_qty: int = Field(ge=0, description="当前日均销量（用于估算收益变化）")
    observations: list[ObservationInput] = Field(
        ..., min_length=0,
        description="历史 price-qty 观测点，≥14 点走 log-log，不足走 prior",
    )
    store_id: Optional[str] = None


# ── 端点 ────────────────────────────────────────────────────────

@router.post("/suggest", response_model=dict)
async def suggest_pricing(
    req: SuggestRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成单菜品定价建议（status='plan'）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(req.dish_id, "dish_id")

    observations = [
        PricingObservation(
            day=o.day, price_fen=o.price_fen, quantity_sold=o.quantity_sold
        )
        for o in req.observations
    ]

    service = DishDynamicPricingService()
    suggestion = await service.suggest_pricing(
        dish_id=req.dish_id,
        dish_name=req.dish_name,
        current_price_fen=req.current_price_fen,
        cost_fen=req.cost_fen,
        current_daily_qty=req.current_daily_qty,
        observations=observations,
    )

    if not suggestion.constraint_check.get("margin_floor_passed"):
        # 本 PR 仍持久化（方便审计），但标记 rejected 建议
        logger.warning(
            "dish_pricing_margin_floor_violation dish=%s current_margin=%s",
            req.dish_name, suggestion.current_margin_rate,
        )

    try:
        suggestion_id = await save_suggestion_to_db(
            db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            suggestion=suggestion,
        )
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_save_failed")
        raise HTTPException(status_code=500, detail=f"建议持久化失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "suggestion_id": suggestion_id,
            "dish_id": suggestion.dish_id,
            "dish_name": suggestion.dish_name,
            "current_price_fen": suggestion.current_price_fen,
            "suggested_price_fen": suggestion.suggested_price_fen,
            "price_change_pct": suggestion.price_change_pct,
            "current_margin_rate": suggestion.current_margin_rate,
            "suggested_margin_rate": suggestion.suggested_margin_rate,
            "elasticity": {
                "value": suggestion.elasticity.elasticity,
                "confidence": suggestion.elasticity.confidence,
                "source": suggestion.elasticity.source,
                "data_points": suggestion.elasticity.data_points,
            },
            "expected_daily_qty_delta": suggestion.expected_daily_qty_delta,
            "expected_daily_margin_delta_fen": suggestion.expected_daily_margin_delta_fen,
            "constraint_check": suggestion.constraint_check,
            "sonnet_analysis": suggestion.sonnet_analysis,
            "sonnet_risk_level": suggestion.sonnet_risk_level,
            "status": "plan",
        },
    }


@router.post("/confirm/{suggestion_id}", response_model=dict)
async def confirm_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """店长确认建议（plan → human_confirmed）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(suggestion_id, "suggestion_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        ok = await transition_status(
            db,
            tenant_id=x_tenant_id,
            suggestion_id=suggestion_id,
            new_status="human_confirmed",
            operator_id=x_operator_id,
        )
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_confirm_failed")
        raise HTTPException(status_code=500, detail=f"确认失败: {exc}") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="suggestion 不存在或状态不允许确认")

    return {"ok": True, "data": {"suggestion_id": suggestion_id, "status": "human_confirmed"}}


@router.post("/apply/{suggestion_id}", response_model=dict)
async def apply_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """应用价格到 dishes 表（human_confirmed → applied）

    注：本 PR 只做状态迁移；真实落价到 dishes.price_fen 由独立 worker 监听
    status='applied' 事件驱动（避免本端点直接修改 dishes，保持事务边界清晰）。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(suggestion_id, "suggestion_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        ok = await transition_status(
            db,
            tenant_id=x_tenant_id,
            suggestion_id=suggestion_id,
            new_status="applied",
            operator_id=x_operator_id,
        )
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_apply_failed")
        raise HTTPException(status_code=500, detail=f"应用失败: {exc}") from exc

    if not ok:
        raise HTTPException(
            status_code=404,
            detail="suggestion 不存在或状态非 human_confirmed，无法 apply",
        )

    return {
        "ok": True,
        "data": {
            "suggestion_id": suggestion_id,
            "status": "applied",
            "message": "状态已迁移，worker 将异步更新 dishes.price_fen",
        },
    }


@router.post("/reject/{suggestion_id}", response_model=dict)
async def reject_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """店长拒绝建议"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(suggestion_id, "suggestion_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        ok = await transition_status(
            db,
            tenant_id=x_tenant_id,
            suggestion_id=suggestion_id,
            new_status="rejected",
            operator_id=x_operator_id,
        )
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_reject_failed")
        raise HTTPException(status_code=500, detail=f"拒绝失败: {exc}") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="suggestion 不存在或状态不允许拒绝")

    return {"ok": True, "data": {"suggestion_id": suggestion_id, "status": "rejected"}}


@router.post("/revert/{suggestion_id}", response_model=dict)
async def revert_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """回滚已应用的调价（applied → reverted）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(suggestion_id, "suggestion_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        ok = await transition_status(
            db,
            tenant_id=x_tenant_id,
            suggestion_id=suggestion_id,
            new_status="reverted",
            operator_id=x_operator_id,
        )
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_revert_failed")
        raise HTTPException(status_code=500, detail=f"回滚失败: {exc}") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="suggestion 不存在或状态非 applied")

    return {"ok": True, "data": {"suggestion_id": suggestion_id, "status": "reverted"}}


@router.get("/summary", response_model=dict)
async def pricing_summary(
    months_back: int = 3,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """租户 N 月定价建议汇总（按 status + risk_level）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if months_back < 1 or months_back > 12:
        raise HTTPException(status_code=400, detail="months_back ∈ [1, 12]")

    try:
        result = await db.execute(text("""
            SELECT
                status,
                sonnet_risk_level,
                COUNT(*)                                         AS total,
                COUNT(*) FILTER (WHERE price_change_pct > 0)     AS price_up_count,
                COUNT(*) FILTER (WHERE price_change_pct < 0)     AS price_down_count,
                AVG(price_change_pct)                            AS avg_change_pct,
                AVG(suggested_margin_rate)                       AS avg_suggested_margin,
                COALESCE(SUM(expected_daily_margin_delta_fen), 0)::bigint AS expected_total_margin_delta_fen,
                COALESCE(SUM(actual_margin_delta_fen), 0)::bigint         AS actual_total_margin_delta_fen
            FROM dish_pricing_suggestions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND created_at >= CURRENT_DATE - (:months_back || ' months')::interval
            GROUP BY status, sonnet_risk_level
            ORDER BY status, sonnet_risk_level NULLS LAST
        """), {"tenant_id": x_tenant_id, "months_back": str(months_back)})
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dish_pricing_summary_failed")
        raise HTTPException(status_code=500, detail=f"汇总失败: {exc}") from exc

    for r in rows:
        for k in ("avg_change_pct", "avg_suggested_margin"):
            if r.get(k) is not None:
                r[k] = float(r[k])

    total_expected = sum(int(r.get("expected_total_margin_delta_fen") or 0) for r in rows)
    total_actual = sum(int(r.get("actual_total_margin_delta_fen") or 0) for r in rows)

    return {
        "ok": True,
        "data": {
            "period": {"months_back": months_back},
            "by_status_risk": rows,
            "aggregate": {
                "expected_total_margin_delta_fen": total_expected,
                "expected_total_margin_delta_yuan": round(total_expected / 100, 2),
                "actual_total_margin_delta_fen": total_actual,
                "actual_total_margin_delta_yuan": round(total_actual / 100, 2),
                "actual_vs_expected_pct": (
                    round(total_actual / total_expected * 100, 2)
                    if total_expected > 0 else None
                ),
            },
        },
    }


# ── 辅助 ────────────────────────────────────────────────────────

def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
