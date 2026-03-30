"""Gateway 中间件 — 租户隔离 + 请求日志"""
import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger()

TENANT_EXEMPT_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/",
)


class TenantMiddleware(BaseHTTPMiddleware):
    """从 X-Tenant-ID header 提取租户 ID，注入 request.state。

    安全策略：
    - 白名单路径（健康检查/认证/文档）免检
    - 其余路径必须携带合法 UUID 格式的 X-Tenant-ID，否则 403
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(prefix) for prefix in TENANT_EXEMPT_PREFIXES):
            request.state.tenant_id = None
            return await call_next(request)

        tenant_id = request.headers.get("X-Tenant-ID")

        if not tenant_id:
            logger.warning("missing_tenant_id", path=path, method=request.method)
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "data": None,
                    "error": {"code": "MISSING_TENANT", "message": "X-Tenant-ID header is required"},
                },
            )

        try:
            uuid.UUID(tenant_id)
        except ValueError:
            logger.warning("invalid_tenant_id", path=path, tenant_id=tenant_id)
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "data": None,
                    "error": {"code": "INVALID_TENANT", "message": "X-Tenant-ID must be a valid UUID"},
                },
            )

        request.state.tenant_id = tenant_id
        response = await call_next(request)
        return response


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求日志 — structlog JSON 格式"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            tenant_id=getattr(request.state, "tenant_id", None),
        )
        return response
