"""Gateway 中间件包
将 middleware.py 的内容内联在此，以兼容 middleware/ 包目录优先于 middleware.py 模块的 Python 规则。
"""
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

        # 双重验证：JWT token 中的 tenant_id 必须与 header 一致
        # TODO(security): AuthMiddleware 当前未注册到主 app（仅存在于 main.py 顶部的
        #   废弃 app 实例）。待 AuthMiddleware 正式接入主 app 后，AuthMiddleware 会在
        #   TenantMiddleware 之前执行并将 JWT payload 中的 tenant_id 写入
        #   request.state.tenant_id（覆盖）。届时需确认：
        #   1. AuthMiddleware 额外写入 request.state.tenant_id_from_token
        #   2. 下方校验逻辑生效，防止 header 伪造租户 ID
        token_tenant = getattr(request.state, "tenant_id_from_token", None)
        if token_tenant and token_tenant != tenant_id:
            logger.warning(
                "tenant_id_mismatch",
                path=path,
                header_tenant=tenant_id,
                token_tenant=token_tenant,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "data": None,
                    "error": {"code": "TENANT_MISMATCH", "message": "Tenant ID mismatch between header and token"},
                },
            )

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


from .auth_middleware import AuthMiddleware

__all__ = ["AuthMiddleware", "TenantMiddleware", "RequestLogMiddleware"]
