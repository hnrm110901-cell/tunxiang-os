"""TunxiangOS API — MVP单体入口

单人团队的正确选择：1个进程，内部模块化。
等有第2个开发者或客户>20家时再拆微服务。

启动: uvicorn services.tunxiang_api.src.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-Native Restaurant Chain Operating System — MVP Monolith",
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
# TODO: 启用后取消注释
# from .shared.middleware import TenantMiddleware, RequestLogMiddleware
# app.add_middleware(RequestLogMiddleware)
# app.add_middleware(TenantMiddleware)

# Routes — 按模块注册，未来可一键拆出
from .api.v1 import auth_routes, hub_routes, trade_routes, ops_routes, brain_routes

app.include_router(auth_routes.router)
app.include_router(hub_routes.router)
app.include_router(trade_routes.router)
app.include_router(ops_routes.router)
app.include_router(brain_routes.router)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "data": {
            "service": "tunxiang-api",
            "version": settings.APP_VERSION,
            "mode": "monolith",
        },
    }
