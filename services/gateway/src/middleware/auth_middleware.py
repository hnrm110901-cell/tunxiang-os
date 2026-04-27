"""JWT 认证中间件 — Gateway 层统一鉴权

职责：
  - 从 Authorization: Bearer <token> 提取 JWT
  - 验证签名和过期时间（复用 JWTService）
  - 提取 tenant_id / user_id / role 注入 request.state
  - 白名单路径跳过验证
  - 无效 token 返回 401

环境变量：
  TX_AUTH_ENABLED  — 设为 "false" 跳过全部认证（仅开发模式）
"""

import os
from typing import Sequence

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# 免认证白名单路径前缀
AUTH_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/wecom/callback",
)

# 免认证白名单路径（精确匹配）
AUTH_EXEMPT_EXACT: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/openapi.json",
    }
)


def _is_exempt(path: str) -> bool:
    """检查路径是否在免认证白名单中。"""
    if path in AUTH_EXEMPT_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT + API Key 二选一认证中间件。

    优先级：
      1. 如有 X-API-Key header → 走 API Key 验证（由 ApiKeyMiddleware 处理，此处跳过）
      2. 如有 Authorization: Bearer <token> → 验证 JWT
      3. 两者都没有 → 401

    TX_AUTH_ENABLED=false 时，所有请求注入 mock 用户信息直接放行。
    """

    def __init__(self, app, exempt_prefixes: Sequence[str] | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self._auth_enabled = os.getenv("TX_AUTH_ENABLED", "true").lower() != "false"
        if exempt_prefixes:
            self._extra_exempt = tuple(exempt_prefixes)
        else:
            self._extra_exempt = ()

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        # 开发模式：跳过认证，注入 mock 数据
        if not self._auth_enabled:
            request.state.user_id = "dev-user-mock"
            request.state.tenant_id = (
                getattr(request.state, "tenant_id", None) or "a0000000-0000-0000-0000-000000000001"
            )
            request.state.role = "admin"
            request.state.mfa_verified = False
            request.state.auth_method = "dev_bypass"
            return await call_next(request)

        path = request.url.path

        # 白名单路径免验证
        if _is_exempt(path) or any(path.startswith(p) for p in self._extra_exempt):
            request.state.user_id = None
            request.state.role = None
            request.state.auth_method = None
            return await call_next(request)

        # API Key 优先（如果已被 ApiKeyMiddleware 设置，直接放行）
        if getattr(request.state, "auth_method", None) == "api_key":
            return await call_next(request)

        # 有 X-API-Key 但还没被处理（不应该发生，但防御性编程）
        if request.headers.get("X-API-Key"):
            request.state.auth_method = "api_key_pending"
            return await call_next(request)

        # JWT 验证
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("auth_missing_token", path=path, method=request.method)
            return _error_response(401, "AUTH_REQUIRED", "Authorization header with Bearer token is required")

        token = auth_header[7:]  # 去掉 "Bearer " 前缀
        if not token:
            return _error_response(401, "AUTH_REQUIRED", "Bearer token is empty")

        # 使用 JWTService 验证
        from ..services.jwt_service import JWTService

        jwt_service = JWTService()
        payload = jwt_service.verify_access_token(token)

        if payload is None:
            logger.warning("auth_invalid_token", path=path, method=request.method)
            return _error_response(401, "AUTH_INVALID_TOKEN", "Invalid or expired token")

        # 注入用户信息到 request.state
        request.state.user_id = payload.get("sub", "")
        request.state.tenant_id = payload.get("tenant_id", "")
        request.state.role = payload.get("role", "")
        request.state.mfa_verified = payload.get("mfa_verified", False)
        request.state.auth_method = "jwt"
        request.state.jwt_jti = payload.get("jti", "")

        logger.debug(
            "auth_jwt_verified",
            user_id=request.state.user_id,
            tenant_id=request.state.tenant_id,
            role=request.state.role,
            path=path,
        )

        return await call_next(request)
