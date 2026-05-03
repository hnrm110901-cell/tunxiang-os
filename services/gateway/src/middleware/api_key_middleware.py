"""API Key 认证中间件 — ISV/开发者 API 调用

职责：
  - 从 X-API-Key header 提取 API Key
  - 验证 Key 有效性（查询 api_applications 表）
  - 提取 tenant_id / scopes / rate_limit 注入 request.state
  - 与 JWT 认证二选一：有 API Key 则不需要 JWT

环境变量：
  TX_AUTH_ENABLED  — 设为 "false" 时跳过验证
"""

import os
from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """API Key 验证中间件。

    仅在请求携带 X-API-Key header 时激活。
    验证成功后设置 request.state.auth_method = "api_key"，
    使得后续 AuthMiddleware 跳过 JWT 验证。

    当前实现：
      - 数据库可用时：查询 api_applications 表验证
      - 数据库不可用时：仅做格式检查 + 日志告警（降级模式）
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self._auth_enabled = os.getenv("TX_AUTH_ENABLED", "true").lower() != "false"

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        api_key = request.headers.get("X-API-Key")

        # 没有 API Key，跳过，让 AuthMiddleware 处理 JWT
        if not api_key:
            return await call_next(request)

        # 开发模式：跳过验证
        if not self._auth_enabled:
            request.state.auth_method = "api_key"
            request.state.api_key_app_id = "dev-app-mock"
            request.state.api_key_scopes = ["*"]
            request.state.api_key_rate_limit = 1000
            if not getattr(request.state, "tenant_id", None):
                request.state.tenant_id = "a0000000-0000-0000-0000-000000000001"
            return await call_next(request)

        # 格式校验：API Key 应以 txapp_ 或 txat_ 开头
        if not api_key.startswith(("txapp_", "txat_")):
            logger.warning("api_key_invalid_format", key_prefix=api_key[:10])
            return _error_response(401, "INVALID_API_KEY", "API Key format is invalid")

        # 尝试查询数据库验证
        app_info = await self._verify_api_key(api_key)

        if app_info is None:
            logger.warning(
                "api_key_verification_failed",
                key_prefix=api_key[:10],
                path=request.url.path,
            )
            return _error_response(401, "INVALID_API_KEY", "API Key is invalid or revoked")

        # 注入认证信息
        request.state.auth_method = "api_key"
        request.state.user_id = f"app:{app_info['app_id']}"
        request.state.tenant_id = app_info["tenant_id"]
        request.state.api_key_app_id = app_info["app_id"]
        request.state.api_key_scopes = app_info["scopes"]
        request.state.api_key_rate_limit = app_info["rate_limit_per_min"]
        request.state.role = "api_client"

        logger.info(
            "api_key_authenticated",
            app_id=app_info["app_id"],
            tenant_id=app_info["tenant_id"],
            path=request.url.path,
        )

        return await call_next(request)

    async def _verify_api_key(self, api_key: str) -> "Optional[dict]":
        """验证 API Key，返回应用信息或 None。

        查询 api_applications 表，校验 app_key 匹配、状态为 active。
        数据库不可用时返回 None（拒绝请求，安全优先）。
        """
        try:
            from shared.ontology.src.database import async_session_factory
        except ImportError:
            logger.warning("api_key_db_not_available", degraded=True)
            return None

        try:
            from sqlalchemy import text

            async with async_session_factory() as session:
                result = await session.execute(
                    text("""
                        SELECT id, tenant_id::text, app_name, scopes,
                               rate_limit_per_min, status
                        FROM api_applications
                        WHERE app_key = :app_key AND status = 'active'
                        LIMIT 1
                    """),
                    {"app_key": api_key},
                )
                row = result.mappings().first()

                if not row:
                    return None

                return {
                    "app_id": str(row["id"]),
                    "tenant_id": row["tenant_id"],
                    "app_name": row["app_name"],
                    "scopes": row["scopes"] if isinstance(row["scopes"], list) else [],
                    "rate_limit_per_min": row["rate_limit_per_min"] or 60,
                }
        except Exception as exc:  # noqa: BLE001 — DB 不可用时优雅降级而非 500
            logger.warning("api_key_db_error", error=str(exc), exc_info=True)
            return None
