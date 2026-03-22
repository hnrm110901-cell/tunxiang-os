"""Gateway 中间件 — 租户隔离 + 请求日志"""
import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()


class TenantMiddleware(BaseHTTPMiddleware):
    """从 X-Tenant-ID header 提取租户 ID，注入 request.state"""

    async def dispatch(self, request: Request, call_next):
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            try:
                uuid.UUID(tenant_id)
            except ValueError:
                from .response import err
                return err("Invalid X-Tenant-ID format", code="INVALID_TENANT", status_code=400)

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
