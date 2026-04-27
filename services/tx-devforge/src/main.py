"""tx-devforge — 屯象 OS 内部研发运维平台后端 (port 8017)。

职责：
- DevForge 应用目录、CMDB、CI/CD 编排、巡检告警的统一后端
- 与 tx-forge（外部 ISV 市场）严格区分

完整规划见 docs/devforge-platform-plan.md。
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import application_router, health_router
from .config import get_settings
from .middlewares import TenantMiddleware
from .utils import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="TunxiangOS tx-devforge",
    version=settings.service_version,
    description="屯象 OS 内部研发运维平台后端（DevForge）",
)

# Prometheus
Instrumentator().instrument(app).expose(app)

# CORS
_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# 租户中间件（先于业务依赖执行）
app.add_middleware(TenantMiddleware)

# 路由注册
app.include_router(health_router)
app.include_router(application_router)


# --- 全局异常处理器 — 统一响应 {ok, data, error} ---


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        error_payload = detail
    else:
        error_payload = {"code": "http_error", "message": str(detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "data": {}, "error": error_payload},
    )


@app.exception_handler(SQLAlchemyError)
async def _sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    logger.exception(
        "devforge_db_error",
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "data": {},
            "error": {"code": "db_error", "message": "internal database error"},
        },
    )


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "ok": False,
            "data": {},
            "error": {"code": "bad_request", "message": str(exc)},
        },
    )


@app.on_event("startup")
async def _on_startup() -> None:
    logger.info(
        "tx_devforge_started",
        service=settings.service_name,
        version=settings.service_version,
        port=settings.port,
    )
