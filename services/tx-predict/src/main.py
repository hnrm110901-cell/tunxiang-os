"""tx-predict — 预测引擎微服务 (port 8013)

屯象OS V6.0 核心模块，对标 Toast IQ / Fourth iQ 需求预测能力。

功能域：
  - 客流预测（历史订单时序 + 天气/节假日修正）
  - 菜品需求预测（加权移动平均 + 多维修正）
  - 营收预测（客流 x 客单价）
  - 天气数据集成（和风天气 API）
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

logger = structlog.get_logger()

from .api.demand_forecast_routes import router as demand_router
from .api.revenue_forecast_routes import router as revenue_router
from .api.traffic_forecast_routes import router as traffic_router
from .api.weather_routes import router as weather_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("tx_predict_started", port=8013)
    yield
    logger.info("tx_predict_stopped")


app = FastAPI(
    title="TunxiangOS tx-predict",
    version="1.0.0",
    description="预测引擎：客流/需求/营收/天气",
    lifespan=lifespan,
)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

app.include_router(traffic_router)
app.include_router(demand_router)
app.include_router(revenue_router)
app.include_router(weather_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-predict", "version": "1.0.0"}}
