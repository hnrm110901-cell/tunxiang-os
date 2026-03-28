"""tx-analytics — 域G 经营分析微服务"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

from .api.analytics import router as analytics_router
from .api.etl import router as etl_router
from .etl.scheduler import get_etl_scheduler

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = get_etl_scheduler()
    scheduler.start()
    logger.info("tx_analytics_started", etl_scheduler="running")
    yield
    scheduler.shutdown()
    logger.info("tx_analytics_stopped")


app = FastAPI(title="TunxiangOS tx-analytics", version="3.0.0", lifespan=lifespan)
app.include_router(analytics_router)
app.include_router(etl_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-analytics", "version": "3.0.0"}}
