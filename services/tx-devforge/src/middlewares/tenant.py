"""TenantMiddleware — 校验 X-Tenant-ID header，确保所有业务接口走 RLS。

策略：
- 健康/可观测路径（/health, /readiness, /metrics, /docs, /openapi.json, /redoc）放行
- 其它路径必须携带合法 UUID 形式的 X-Tenant-ID，否则 401
- 校验通过后将 tenant_id 写入 request.state.tenant_id，供后续依赖使用
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..db import TenantIDInvalid, TenantIDMissing, validate_tenant_id

logger = structlog.get_logger(__name__)

_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/readiness",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    # FastAPI swagger 静态资源
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    return False


class TenantMiddleware(BaseHTTPMiddleware):
    """提取并校验 X-Tenant-ID header。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _is_public(request.url.path):
            return await call_next(request)

        raw = request.headers.get("X-Tenant-ID") or request.headers.get("x-tenant-id")
        try:
            tenant_id = validate_tenant_id(raw)
        except TenantIDMissing:
            logger.info(
                "devforge_tenant_missing",
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "data": {},
                    "error": {
                        "code": "tenant_required",
                        "message": "X-Tenant-ID header is required",
                    },
                },
            )
        except TenantIDInvalid as exc:
            logger.info(
                "devforge_tenant_invalid",
                path=request.url.path,
                method=request.method,
                error=str(exc),
            )
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "data": {},
                    "error": {
                        "code": "tenant_invalid",
                        "message": "X-Tenant-ID must be a valid UUID",
                    },
                },
            )

        request.state.tenant_id = tenant_id
        return await call_next(request)
