"""天气数据集成 API 路由

端点：
  GET /api/v1/predict/weather/{city}    — 获取7天天气预报
  GET /api/v1/predict/weather/impact    — 天气对营业的影响分析
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.weather_service import WeatherService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/predict/weather", tags=["weather"])


# ── 依赖注入 ──

def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 1. 7天天气预报 ──

@router.get(
    "/{city}",
    summary="获取7天天气预报",
    description="调用和风天气API获取指定城市7天预报，含营业影响系数",
)
async def get_weather_forecast(
    city: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    svc = WeatherService()
    try:
        forecast = await svc.get_7day_forecast(city, tenant_id, db)
    except (ValueError, KeyError) as exc:
        logger.warning("weather.forecast_error", city=city, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "ok": True,
        "data": {
            "city": city,
            "forecast_days": len(forecast),
            "daily": forecast,
        },
    }


# ── 2. 天气影响分析 ──

@router.get(
    "/impact",
    summary="天气对营业的影响分析",
    description="分析未来7天天气对客流/营收的影响，含运营建议",
)
async def get_weather_impact(
    city: str = Query(..., description="城市名"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    svc = WeatherService()
    try:
        impact = await svc.analyze_weather_impact(city, tenant_id, db)
    except (ValueError, KeyError) as exc:
        logger.warning("weather.impact_error", city=city, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {"ok": True, "data": impact}
