"""InternalJwtMiddleware — 下游服务校验 X-Internal-JWT，把受信 claims 写入 request.state

审计 S-02（P0）闭环 part 2：PR #195 已让 gateway proxy 在受信路径附加 X-Internal-JWT
header 但下游服务从未挂校验中间件 —— 即"只签不验"，S-02 完成度 50%。

本中间件作用：
  - 在每个下游 service（tx-trade / tx-pay / tx-member 等）启动时挂载
  - 拦截每个进入的 HTTP 请求
  - 校验 X-Internal-JWT header（HS256 + iss=tx-gateway + aud=tx-internal + 有效期 60s）
  - 通过 → request.state.{tenant_id, user_id, role, auth_method = "internal_jwt"}
  - 失败 → 401 JSON 响应（不让 FastAPI 默认 HTML 页泄漏堆栈）
  - 服务路由的 _get_tenant_id() 优先读 request.state.tenant_id，
    fallback 到 X-Tenant-ID header（向后兼容期）

环境兼容：
  TX_INTERNAL_JWT_SECRET 未配置 + 非生产 → 跳过校验（warn 一次后静默），保持 dev 兼容
  TX_INTERNAL_JWT_SECRET 未配置 + 生产 (TX_ENV in {production,prod,gray})
    → __init__ 阶段已经被 internal_jwt._get_secret() raise（fail-closed）

豁免路径（platform 端点，gateway 不会注入 JWT）：
  /health, /healthz, /metrics, /docs, /openapi.json, /redoc, /favicon.ico

性能：
  - HS256 校验本身 < 0.1ms；模块级 import + lazy lookup secret，每请求开销 < 1ms
  - 用 ASGI middleware 接口（继承 BaseHTTPMiddleware）支持 starlette/fastapi 标准流程

挂载示例：
    from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware
    app.add_middleware(InternalJwtMiddleware)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .internal_jwt import InternalJwtError, verify_internal_jwt

logger = logging.getLogger(__name__)

# 平台端点豁免：gateway 不会注入 JWT，这些路径必须放行
_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/healthz",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico",
    }
)
_EXEMPT_PREFIXES = (
    "/docs/",
    "/redoc/",
    "/static/",
)

_PRODUCTION_ENVS = ("production", "prod", "gray")


def _is_production() -> bool:
    env = (os.environ.get("TX_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    return env in _PRODUCTION_ENVS


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_PATHS:
        return True
    return any(path.startswith(p) for p in _EXEMPT_PREFIXES)


def _has_secret() -> bool:
    return bool(os.environ.get("TX_INTERNAL_JWT_SECRET", "").strip())


def _err(message: str, code: str = "INTERNAL_JWT_INVALID") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


class InternalJwtMiddleware(BaseHTTPMiddleware):
    """校验 gateway 注入的 X-Internal-JWT，把 claims 写入 request.state。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # 1. 平台端点豁免
        if _is_exempt(path):
            return await call_next(request)

        # 2. dev/staging 无 secret → 跳过校验（warn 仅一次靠 logger 自身去重）
        if not _has_secret():
            if _is_production():
                # 理论上 internal_jwt._get_secret() 启动期已拒；保险兜底
                logger.error("internal_jwt_middleware_no_secret_in_production path=%s", path)
                return _err("internal jwt secret not configured", code="INTERNAL_JWT_NOT_CONFIGURED")
            logger.debug("internal_jwt_middleware_skip_no_secret path=%s", path)
            return await call_next(request)

        # 3. 取 header
        token = request.headers.get("X-Internal-JWT", "").strip()
        if not token:
            # 生产模式必须有 token；缺失 = 来自 gateway 之外（攻击或配置错误）
            if _is_production():
                client_host = request.client.host if request.client else "unknown"
                logger.warning(
                    "internal_jwt_middleware_missing_token path=%s client=%s",
                    path,
                    client_host,
                )
                return _err("X-Internal-JWT header required")
            # 非生产：缺 token 也放行（兼容老 client / 未升级测试），不 warn 太频繁
            return await call_next(request)

        # 4. 校验
        try:
            claims = verify_internal_jwt(token)
        except InternalJwtError as exc:
            logger.warning(
                "internal_jwt_middleware_verify_failed path=%s error=%s",
                path,
                exc,
            )
            return _err(f"internal jwt invalid: {exc}")

        # 5. 注入 request.state（路由层 _get_tenant_id 会优先读这里）
        request.state.tenant_id = claims.get("tenant_id", "")
        request.state.user_id = claims.get("user_id", "") or None
        request.state.role = claims.get("role", "") or None
        request.state.auth_method = "internal_jwt"
        request.state.internal_jwt_claims = claims

        return await call_next(request)
