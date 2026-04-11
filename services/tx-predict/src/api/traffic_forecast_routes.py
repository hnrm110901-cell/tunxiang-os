"""客流预测 API 路由

端点：
  GET  /api/v1/predict/traffic/{store_id}        — 未来7天小时级客流预测
  GET  /api/v1/predict/traffic/{store_id}/today   — 今日剩余时段客流预测
  POST /api/v1/predict/traffic/train              — 触发模型训练
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.traffic_predictor import TrafficPredictor

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/predict/traffic", tags=["traffic-forecast"])


# ── 依赖注入 ──

def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 1. 未来7天小时级客流预测 ──

@router.get(
    "/{store_id}",
    summary="未来7天小时级客流预测",
    description="基于历史订单数据 + 天气/节假日修正，返回7天 x 24小时的预测矩阵",
)
async def get_traffic_forecast_7days(
    store_id: str,
    city: Optional[str] = Query(None, description="城市名（用于天气修正）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = TrafficPredictor()
    try:
        result = await predictor.forecast_7days(store_id, tenant_id, db, city=city)
    except (ValueError, KeyError) as exc:
        logger.warning("traffic_forecast.7days_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}


# ── 2. 今日剩余时段客流预测 ──

@router.get(
    "/{store_id}/today",
    summary="今日剩余时段客流预测",
    description="预测当日剩余小时的客流量，含已产生实际客流数",
)
async def get_traffic_forecast_today(
    store_id: str,
    city: Optional[str] = Query(None, description="城市名"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = TrafficPredictor()
    try:
        result = await predictor.forecast_today_remaining(store_id, tenant_id, db, city=city)
    except (ValueError, KeyError) as exc:
        logger.warning("traffic_forecast.today_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}


# ── 3. 触发模型训练 ──

@router.post(
    "/train",
    summary="触发客流预测模型训练",
    description="基于历史订单数据重新计算客流基线，结果缓存到 prediction_results 表",
)
async def trigger_traffic_train(
    store_id: str = Query(..., description="门店ID"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    predictor = TrafficPredictor()
    try:
        result = await predictor.trigger_train(store_id, tenant_id, db)
    except (ValueError, KeyError) as exc:
        logger.warning("traffic_forecast.train_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": result}
