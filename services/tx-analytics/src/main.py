"""tx-analytics — 域G 经营分析微服务"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

from .api.analytics import router as analytics_router
from .api.etl import router as etl_router
from .etl.scheduler import get_etl_scheduler

logger = structlog.get_logger()

from .api.boss_bi_routes import router as boss_bi_router
from .api.cost_health_routes import router as cost_health_router
from .api.dashboard_routes import router as dashboard_router
from .api.dish_analysis_routes import router as dish_analysis_router
from .api.group_dashboard_routes import router as group_dashboard_router
from .api.private_domain_routes import router as private_domain_router
from .api.knowledge_query import router as knowledge_router
from .api.inventory_analysis_routes import router as inventory_analysis_router
from .api.report_routes import router as report_router
from .api.reports_router import router as p0_reports_router
from .api.store_analysis_routes import router as store_analysis_router
from .api.stream_report_routes import router as stream_report_router
from .api.report_config_routes import router as report_config_router
from .api.narrative_enhanced_routes import router as narrative_enhanced_router  # P3-02

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = get_etl_scheduler()
    scheduler.start()
    logger.info("tx_analytics_started", etl_scheduler="running")
    yield
    scheduler.shutdown()
    logger.info("tx_analytics_stopped")


app = FastAPI(title="TunxiangOS tx-analytics", version="3.0.0", lifespan=lifespan)

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

app.include_router(analytics_router)
app.include_router(etl_router)

app.include_router(dashboard_router)
app.include_router(store_analysis_router)
app.include_router(dish_analysis_router)
app.include_router(report_router)
app.include_router(private_domain_router)
app.include_router(knowledge_router)
app.include_router(inventory_analysis_router)
app.include_router(p0_reports_router)
app.include_router(cost_health_router)
app.include_router(boss_bi_router)
app.include_router(stream_report_router)
app.include_router(group_dashboard_router)
app.include_router(report_config_router)
app.include_router(narrative_enhanced_router)  # P3-02 对比叙事+异常叙事

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-analytics", "version": "3.0.0"}}
