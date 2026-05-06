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

环境兼容（cutover 完成后已收紧）：
  TX_INTERNAL_JWT_SECRET 必须配置（dev / staging / prod 全环境）
  缺 secret → 500 fail-closed；缺 token → 401（无论 env）
  历史 dev/staging 跳过校验路径已删除（cleanup commit；详见 docs/security/cutover-cleanup-plan.md §3.3）

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
import re
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
# 外部平台 webhook 豁免：美团/饿了么/抖音/微信/企业微信/钉钉/小红书 等回调走公网入口，
# 不经 gateway，不带 X-Internal-JWT。这些路径必须有自己的签名校验（已在各 webhook
# 路由内部实现）。匹配 `/webhook` 或 `/webhooks` 作为路径段（前后必须 `/` 或路径末尾）。
# 已审计 11 个文件 19 个 webhook endpoint 全部位于 services/tx-trade、tx-org，全部
# 含外部平台签名校验。新增 webhook endpoint 必须确认含签名校验后才合法。
_EXEMPT_REGEX = re.compile(r"/webhooks?(/|$)")


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_PATHS:
        return True
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return True
    if _EXEMPT_REGEX.search(path):
        return True
    return False


def _has_secret() -> bool:
    return bool(os.environ.get("TX_INTERNAL_JWT_SECRET", "").strip())


def _err(message: str, code: str = "INTERNAL_JWT_INVALID", status_code: int = 401) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
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

        # 2. cutover 后强制 fail-closed：缺 secret = 服务器配置错误（500，不是 401）
        if not _has_secret():
            logger.error("internal_jwt_middleware_no_secret path=%s", path)
            return _err(
                "internal jwt secret not configured",
                code="INTERNAL_JWT_NOT_CONFIGURED",
                status_code=500,
            )

        # 3. 取 header — cutover 后 dev/staging 也强制要 token（无 token = 来自 gateway 之外）
        token = request.headers.get("X-Internal-JWT", "").strip()
        if not token:
            client_host = request.client.host if request.client else "unknown"
            logger.warning(
                "internal_jwt_middleware_missing_token path=%s client=%s",
                path,
                client_host,
            )
            return _err("X-Internal-JWT header required")

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
