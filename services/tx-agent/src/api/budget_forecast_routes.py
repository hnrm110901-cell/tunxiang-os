"""Sprint D4c — AI预算预测 API

端点：
  POST /api/v1/agent/budget/forecast          — 触发下月预算预测
  GET  /api/v1/agent/budget/forecast/latest   — 获取最新预测结果
  GET  /api/v1/agent/budget/alerts            — 预算预警列表
  POST /api/v1/agent/budget/optimize          — AI优化建议
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.budget_forecast_service import (
    BudgetForecastService,
    get_latest_forecast,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/agent/budget",
    tags=["agent-budget-forecast"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class ForecastRequest(BaseModel):
    store_id: Optional[str] = Field(None, description="门店ID（不传=集团预算预测）")
    store_name: Optional[str] = Field(None, max_length=200, description="门店名称（用于 prompt 上下文）")


class OptimizeRequest(BaseModel):
    store_id: Optional[str] = Field(None, description="门店ID（不传=集团）")


# ── 辅助 ─────────────────────────────────────────────────────────


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 非法 UUID: {value!r}") from exc


# ── 端点 ────────────────────────────────────────────────────────


@router.post("/forecast", response_model=dict)
async def trigger_forecast(
    req: ForecastRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """触发下月预算预测（Sonnet 4.7 + Prompt Cache / fallback规则引擎）。

    返回各科目预测金额、置信区间、影响因素和毛利约束校验结果。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    service = BudgetForecastService()
    try:
        forecast = await service.forecast_next_month(
            db=db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            store_name=req.store_name,
        )
    except Exception as exc:
        logger.exception("budget_forecast_failed")
        raise HTTPException(status_code=500, detail=f"预测失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "store_id": forecast.store_id,
            "target_year": forecast.target_year,
            "target_month": forecast.target_month,
            "total_amount_fen": forecast.total_amount_fen,
            "confidence": forecast.confidence,
            "reasoning": forecast.reasoning,
            "factors": forecast.factors,
            "model_id": forecast.model_id,
            "categories": [
                {
                    "category_code": c.category_code,
                    "predicted_amount_fen": c.predicted_amount_fen,
                    "lower_bound_fen": c.lower_bound_fen,
                    "upper_bound_fen": c.upper_bound_fen,
                    "yoy_change_pct": c.yoy_change_pct,
                    "mom_change_pct": c.mom_change_pct,
                }
                for c in forecast.categories
            ],
            "prompt_cache_stats": {
                "cache_read_tokens": forecast.cache_read_tokens,
                "cache_creation_tokens": forecast.cache_creation_tokens,
                "input_tokens": forecast.input_tokens,
                "output_tokens": forecast.output_tokens,
                "cache_hit_rate": forecast.cache_hit_rate,
            },
        },
    }


@router.get("/forecast/latest", response_model=dict)
async def get_latest_forecast_endpoint(
    store_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取最新预测结果（从 agent_decision_logs 读取）。"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    result = await get_latest_forecast(
        db=db,
        tenant_id=x_tenant_id,
        store_id=store_id,
    )

    if not result:
        return {
            "ok": True,
            "data": None,
            "message": "暂无预测记录，请先触发 POST /forecast",
        }

    return {"ok": True, "data": result}


@router.get("/alerts", response_model=dict)
async def get_budget_alerts(
    store_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """预算预警列表。

    规则：
    - 执行率 >80%：warning
    - 执行率 >100%：urgent
    - 连续3月超支：escalation
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    service = BudgetForecastService()
    try:
        alerts = await service.check_budget_alerts(
            db=db,
            tenant_id=x_tenant_id,
            store_id=store_id,
        )
    except Exception as exc:
        logger.exception("budget_alerts_failed")
        raise HTTPException(status_code=500, detail=f"预警查询失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "alerts": [
                {
                    "alert_type": a.alert_type,
                    "category_code": a.category_code,
                    "current_rate": a.current_rate,
                    "message": a.message,
                    "suggested_action": a.suggested_action,
                }
                for a in alerts
            ],
            "summary": {
                "total": len(alerts),
                "urgent_count": sum(1 for a in alerts if a.alert_type == "urgent"),
                "warning_count": sum(1 for a in alerts if a.alert_type == "warning"),
                "escalation_count": sum(1 for a in alerts if a.alert_type == "escalation"),
            },
        },
    }


@router.post("/optimize", response_model=dict)
async def generate_optimization(
    req: OptimizeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """基于AI生成预算优化建议。"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    service = BudgetForecastService()
    try:
        suggestions = await service.generate_optimization_suggestions(
            db=db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
        )
    except Exception as exc:
        logger.exception("budget_optimize_failed")
        raise HTTPException(status_code=500, detail=f"优化建议生成失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "suggestions": suggestions,
            "count": len(suggestions),
        },
    }
