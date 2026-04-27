"""中间件 — 租户隔离 + 请求日志

与 gateway/src/middleware/ 包内中间件职责对齐，适配单体入口（独立实现）。
"""

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("tunxiang-api")


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
    """请求日志 — JSON 格式"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request method=%s path=%s status=%d duration_ms=%.2f tenant_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            getattr(request.state, "tenant_id", None),
        )
        return response
