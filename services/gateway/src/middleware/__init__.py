"""Gateway 中间件包（唯一入口；勿在同目录保留 middleware.py，否则与包名冲突且易被忽略）。

TenantMiddleware 来自 tenant_middleware：JWT claims 优先、X-Tenant-ID 兜底（须晚于 AuthMiddleware）。
"""
import time

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

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


from .auth_middleware import AuthMiddleware
from .tenant_middleware import TenantMiddleware

__all__ = ["AuthMiddleware", "TenantMiddleware", "RequestLogMiddleware"]
