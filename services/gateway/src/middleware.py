"""Gateway 中间件 — JWT 认证 + 租户隔离 + 请求日志"""
import time
import uuid

import jwt
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .response import err

logger = structlog.get_logger()

AUTH_WHITELIST: set[str] = {"/health", "/api/v1/auth/login", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}


def _is_whitelisted(path: str) -> bool:
    return path in AUTH_WHITELIST or path.startswith("/docs") or path.startswith("/redoc")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_whitelisted(request.url.path):
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return err("缺少认证令牌", code="UNAUTHORIZED", status_code=401)
        token = auth_header[7:]
        from .auth import JWT_SECRET, JWT_ALGORITHM
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return err("Token 已过期", code="TOKEN_EXPIRED", status_code=401)
        except jwt.InvalidTokenError:
            return err("Token 无效", code="INVALID_TOKEN", status_code=401)
        jwt_tenant_id = payload.get("tenant_id")
        jwt_user_id = payload.get("user_id")
        jwt_role = payload.get("role")
        jwt_merchant = payload.get("merchant_name")
        header_tenant_id = request.headers.get("X-Tenant-ID")
        effective_tenant_id = jwt_tenant_id
        if header_tenant_id:
            if jwt_role == "superadmin":
                effective_tenant_id = header_tenant_id
                logger.info("superadmin_tenant_switch", user_id=jwt_user_id, from_tenant=jwt_tenant_id, to_tenant=header_tenant_id)
            elif header_tenant_id != jwt_tenant_id:
                logger.warning("tenant_mismatch_rejected", user_id=jwt_user_id, jwt_tenant=jwt_tenant_id, header_tenant=header_tenant_id)
                return err("无权访问该租户数据", code="TENANT_FORBIDDEN", status_code=403)
        request.state.user_id = jwt_user_id
        request.state.tenant_id = effective_tenant_id
        request.state.role = jwt_role
        request.state.merchant_name = jwt_merchant
        return await call_next(request)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id and tenant_id != "platform":
            try:
                uuid.UUID(tenant_id)
            except ValueError:
                return err("Invalid tenant_id format", code="INVALID_TENANT", status_code=400)
        return await call_next(request)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration_ms, tenant_id=getattr(request.state, "tenant_id", None))
        return response
