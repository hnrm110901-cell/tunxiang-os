"""Sprint D3b — 营销活动 ROI 预测 API

端点：
  POST /api/v1/member/campaign/roi/forecast
    入参：{campaign_name, campaign_type, forecast_start, forecast_end, history:[...]}
    出参：forecast record（baseline + uplift + Sonnet 分析）
  POST /api/v1/member/campaign/roi/complete/{forecast_id}
    入参：{actual_by_day: {YYYY-MM-DD: fen}}
    出参：backtest 结果（true_uplift + MAPE + needs_calibration）
  GET  /api/v1/member/campaign/roi/summary
    查询：?months_back=6
    出参：按月/活动类型聚合 ROI 视图
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

from ..services.campaign_roi_forecast_service import (
    CampaignROIForecastService,
    TimeSeriesPoint,
    complete_forecast_with_backtest,
    save_forecast_to_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/member/campaign/roi",
    tags=["member-campaign-roi"],
)


# ── 请求/响应模型 ────────────────────────────────────────────────

class HistoryPoint(BaseModel):
    day: date_cls
    revenue_fen: int = Field(ge=0)


class ForecastRequest(BaseModel):
    """规划期生成 ROI 预测"""
    campaign_name: str = Field(..., max_length=200)
    campaign_type: str = Field(..., description="seasonal/referral/offpeak/new_customer/dormant_recall/banquet")
    forecast_start: date_cls
    forecast_end: date_cls
    history: list[HistoryPoint] = Field(
        ...,
        min_length=2,
        description="至少 2 点历史营收数据；< 30 点走 linear/moving_average",
    )
    uplift_estimate_fen: int = Field(
        default=0, description="活动预期增量（可为负）。业务方可提供 Sonnet 参考"
    )
    store_id: Optional[str] = None
    campaign_id: Optional[str] = None


class CompleteRequest(BaseModel):
    """活动结束回填实际数据"""
    actual_by_day: dict[str, int] = Field(
        ..., description="{YYYY-MM-DD: 分}，活动期实际营收"
    )


# ── 端点 ────────────────────────────────────────────────────────

@router.post("/forecast", response_model=dict)
async def create_forecast(
    req: ForecastRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成活动 ROI 预测并入库 campaign_roi_forecasts（status='plan'）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    if req.forecast_end < req.forecast_start:
        raise HTTPException(status_code=400, detail="forecast_end 早于 forecast_start")

    history = [TimeSeriesPoint(day=p.day, revenue_fen=p.revenue_fen) for p in req.history]

    service = CampaignROIForecastService()
    forecast = await service.forecast_baseline(
        history=history,
        forecast_start=req.forecast_start,
        forecast_end=req.forecast_end,
    )

    if not forecast.baseline_fen_by_day:
        raise HTTPException(
            status_code=422,
            detail=f"无法生成基线预测（history={len(history)} 点不足或日期非法）",
        )

    # Sonnet 分析（backtest=None 表示规划期）
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name=req.campaign_name,
        campaign_type=req.campaign_type,
        forecast=forecast,
        backtest=None,
    )

    try:
        forecast_id = await save_forecast_to_db(
            db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            campaign_id=req.campaign_id,
            campaign_name=req.campaign_name,
            campaign_type=req.campaign_type,
            forecast_start=req.forecast_start,
            forecast_end=req.forecast_end,
            forecast=forecast,
            uplift_forecast_fen=req.uplift_estimate_fen,
            sonnet_analysis=analysis,
            recommended_actions=actions,
        )
    except SQLAlchemyError as exc:
        logger.exception("campaign_roi_save_failed")
        raise HTTPException(status_code=500, detail=f"预测持久化失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "forecast_id": forecast_id,
            "campaign_name": req.campaign_name,
            "forecast_model": forecast.model,
            "baseline_forecast_fen": forecast.baseline_total_fen,
            "uplift_estimate_fen": req.uplift_estimate_fen,
            "confidence": forecast.confidence,
            "sonnet_analysis": analysis,
            "recommended_actions": actions,
            "status": "plan",
        },
    }


@router.post("/complete/{forecast_id}", response_model=dict)
async def complete_forecast(
    forecast_id: str,
    req: CompleteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动结束回填实际值，计算 MAPE 并标记 needs_calibration"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(forecast_id, "forecast_id")

    # 读取原 baseline
    try:
        result = await db.execute(text("""
            SELECT baseline_forecast_fen, forecast_start, forecast_end,
                   campaign_name, campaign_type
            FROM campaign_roi_forecasts
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
            LIMIT 1
        """), {"id": forecast_id, "tenant_id": x_tenant_id})
        row = result.mappings().first()
    except SQLAlchemyError as exc:
        logger.exception("campaign_roi_load_failed")
        raise HTTPException(status_code=500, detail=f"读取预测失败: {exc}") from exc

    if not row:
        raise HTTPException(status_code=404, detail="forecast 不存在或已删除")

    # 解析 actual + baseline（baseline 按日均分摊，简化版）
    actual_by_day: dict[date_cls, int] = {}
    for day_str, fen in req.actual_by_day.items():
        try:
            d = date_cls.fromisoformat(day_str)
            actual_by_day[d] = int(fen)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"日期格式错误: {day_str}，应为 YYYY-MM-DD",
            ) from None

    # 按日均分摊 baseline（生产版应存每日预测，简化版分摊）
    days_total = (row["forecast_end"] - row["forecast_start"]).days + 1
    if days_total <= 0:
        days_total = 1
    per_day_baseline = row["baseline_forecast_fen"] // days_total
    baseline_by_day: dict[date_cls, int] = {}
    current = row["forecast_start"]
    for _ in range(days_total):
        baseline_by_day[current] = per_day_baseline
        current = current.fromordinal(current.toordinal() + 1)

    service = CampaignROIForecastService()
    backtest = service.backtest(baseline_by_day, actual_by_day)

    # Sonnet 解读（backtest 已有）
    from ..services.campaign_roi_forecast_service import ForecastResult
    proxy_forecast = ForecastResult(
        model="prophet",  # 读自 DB，此处作占位
        baseline_total_fen=row["baseline_forecast_fen"],
        confidence=0.0,
    )
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name=row["campaign_name"],
        campaign_type=row["campaign_type"],
        forecast=proxy_forecast,
        backtest=backtest,
    )

    try:
        ok = await complete_forecast_with_backtest(
            db,
            tenant_id=x_tenant_id,
            forecast_id=forecast_id,
            backtest=backtest,
            sonnet_analysis=analysis,
            recommended_actions=actions,
        )
    except SQLAlchemyError as exc:
        logger.exception("campaign_roi_complete_failed")
        raise HTTPException(status_code=500, detail=f"回填失败: {exc}") from exc

    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"forecast_id={forecast_id} 状态不允许 complete（需 plan/running）",
        )

    return {
        "ok": True,
        "data": {
            "forecast_id": forecast_id,
            "true_revenue_fen": backtest.true_revenue_fen,
            "true_baseline_fen": backtest.true_baseline_fen,
            "true_uplift_fen": backtest.true_uplift_fen,
            "mape": backtest.mape,
            "mape_pct": round(backtest.mape * 100, 2),
            "needs_calibration": backtest.needs_calibration,
            "sonnet_analysis": analysis,
            "recommended_actions": actions,
            "status": "completed",
        },
    }


@router.get("/summary", response_model=dict)
async def roi_summary(
    months_back: int = 6,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """租户 N 月内的活动 ROI 聚合（按 campaign_type）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if months_back < 1 or months_back > 36:
        raise HTTPException(status_code=400, detail="months_back 必须在 [1, 36]")

    try:
        result = await db.execute(text("""
            SELECT
                campaign_type,
                COUNT(*)                                     AS total_campaigns,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) FILTER (WHERE needs_calibration)    AS needs_calibration_count,
                COALESCE(SUM(true_uplift_fen), 0)::bigint    AS true_uplift_sum_fen,
                COALESCE(SUM(baseline_forecast_fen), 0)::bigint AS baseline_sum_fen,
                AVG(mape) FILTER (WHERE mape IS NOT NULL)    AS avg_mape,
                AVG(forecast_confidence)                     AS avg_confidence
            FROM campaign_roi_forecasts
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND created_at >= CURRENT_DATE - (:months_back || ' months')::interval
            GROUP BY campaign_type
            ORDER BY true_uplift_sum_fen DESC
        """), {"tenant_id": x_tenant_id, "months_back": str(months_back)})
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("campaign_roi_summary_failed")
        raise HTTPException(status_code=500, detail=f"汇总查询失败: {exc}") from exc

    for r in rows:
        if r.get("avg_mape") is not None:
            r["avg_mape"] = float(r["avg_mape"])
        if r.get("avg_confidence") is not None:
            r["avg_confidence"] = float(r["avg_confidence"])

    total_uplift_fen = sum(int(r.get("true_uplift_sum_fen") or 0) for r in rows)
    total_baseline_fen = sum(int(r.get("baseline_sum_fen") or 0) for r in rows)

    return {
        "ok": True,
        "data": {
            "period": {"months_back": months_back},
            "by_campaign_type": rows,
            "aggregate": {
                "total_uplift_fen": total_uplift_fen,
                "total_uplift_yuan": round(total_uplift_fen / 100, 2),
                "total_baseline_fen": total_baseline_fen,
                "roi_multiplier": (
                    round(total_uplift_fen / total_baseline_fen, 3)
                    if total_baseline_fen > 0 else None
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
