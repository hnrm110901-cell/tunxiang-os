"""菜品需求预测 API 路由

端点：
  GET /api/v1/predict/demand/{store_id}          — 未来3天SKU级需求预测
  GET /api/v1/predict/demand/{store_id}/prep      — 备餐建议（半成品提前准备量）
  GET /api/v1/predict/demand/accuracy             — 预测准确率追踪
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.demand_predictor import DemandPredictor

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/predict/demand", tags=["demand-forecast"])


# ── 依赖注入 ──


def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 1. 未来3天SKU级需求预测 ──


@router.get(
    "/{store_id}",
    summary="未来3天SKU级菜品需求预测",
    description="基于加权移动平均 + 天气/季节/星期修正，返回每道菜的预测需求量",
)
async def get_demand_forecast(
    store_id: str,
    days: int = Query(default=3, ge=1, le=7, description="预测天数"),
    city: Optional[str] = Query(None, description="城市名（天气修正）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = DemandPredictor()
    try:
        result = await predictor.forecast_demand(
            store_id,
            tenant_id,
            db,
            forecast_days=days,
            city=city,
        )
    except (ValueError, KeyError) as exc:
        logger.warning("demand_forecast.error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}


# ── 2. 备餐建议 ──


@router.get(
    "/{store_id}/prep",
    summary="备餐建议（半成品提前准备量）",
    description="基于明日需求预测 x 安全系数，生成备餐清单",
)
async def get_prep_suggestions(
    store_id: str,
    city: Optional[str] = Query(None, description="城市名"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = DemandPredictor()
    try:
        result = await predictor.get_prep_suggestions(store_id, tenant_id, db, city=city)
    except (ValueError, KeyError) as exc:
        logger.warning("demand_forecast.prep_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}


# ── 3. 预测准确率追踪 ──


@router.get(
    "/accuracy",
    summary="预测准确率追踪",
    description="对比过去N天预测值与实际销量，计算MAPE指标",
)
async def get_prediction_accuracy(
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(default=7, ge=1, le=30, description="统计天数"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = DemandPredictor()
    try:
        result = await predictor.get_accuracy(store_id, tenant_id, db, days=days)
    except (ValueError, KeyError) as exc:
        logger.warning("demand_forecast.accuracy_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}
