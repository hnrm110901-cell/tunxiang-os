"""AI 2.0 — 东南亚多市场预测 API

提供跨市场预测、市场就绪度评估、节假日影响分析。
"""
from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Query

from ..services.regional_forecasting_service import RegionalForecastingService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/regional-forecast", tags=["regional-forecast"])
service = RegionalForecastingService()


@router.get("/market/{country_code}", summary="市场配置概况")
async def get_market_overview(country_code: str) -> dict[str, Any]:
    """获取指定市场的配置信息（币种/税率/高峰时段）。"""
    data = service.get_market_overview(country_code)
    return {"ok": True, "data": data, "error": None}


@router.post("/cross-market", summary="跨市场预测扩展")
async def cross_market_forecast(body: dict[str, Any]) -> dict[str, Any]:
    """将基准市场预测扩展到多个目标市场。"""
    result = service.forecast_cross_market(
        base_forecast=body.get("base_forecast", {}),
        target_markets=body.get("target_markets", ["MY", "ID", "VN"]),
    )
    return {"ok": True, "data": result, "error": None}


@router.get("/holiday-impact", summary="多市场节假日影响分析")
async def holiday_impact(
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    markets: str = Query("MY,ID,VN", description="逗号分隔的市场代码"),
) -> dict[str, Any]:
    """分析日期范围内各市场的节假日影响。"""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    market_list = [m.strip() for m in markets.split(",")]
    result = service.get_holiday_impact_multi_market(start_date, end_date, market_list)
    return {"ok": True, "data": result, "error": None}


@router.get("/cuisine/{country_code}", summary="市场菜系推荐")
async def cuisine_recommendations(
    country_code: str,
    season: Optional[str] = Query(None, description="季节筛选"),
) -> dict[str, Any]:
    """获取面向特定市场的菜系优化推荐。"""
    data = service.get_cuisine_recommendations(country_code, season)
    return {"ok": True, "data": {"recommendations": data}, "error": None}


@router.get("/readiness/{country_code}", summary="市场就绪度评估")
async def market_readiness(country_code: str) -> dict[str, Any]:
    """评估指定市场的扩张就绪度。"""
    data = service.assess_market_readiness(country_code)
    return {"ok": True, "data": data, "error": None}
