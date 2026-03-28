"""tx-analytics — 域G 经营分析微服务

门店健康度、经营叙事、场景识别、KPI 监控、报表、竞品分析
来源：34 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.analytics import router as analytics_router
from .api.dashboard_routes import router as dashboard_router
from .api.store_analysis_routes import router as store_analysis_router
from .api.dish_analysis_routes import router as dish_analysis_router

app = FastAPI(title="TunxiangOS tx-analytics", version="3.0.0")
app.include_router(analytics_router)
app.include_router(dashboard_router)
app.include_router(store_analysis_router)
app.include_router(dish_analysis_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-analytics", "version": "3.0.0"}}
