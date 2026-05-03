"""API Key 认证中间件 — ISV/第三方开发者 API 调用

职责：
  - 从 X-API-Key header 提取 API Key
  - 验证 Key 有效性（新表 `api_keys` SHA-256 或旧表 `api_applications`）
  - 提取 tenant_id / permissions / rate_limit 注入 request.state
  - 与 JWT 认证二选一：有 API Key 则不需要 JWT

支持两种密钥格式：
  - tx_xxx... — 新版 API 密钥（api_keys 表，SHA-256 哈希）
  - txapp_xxx... — 旧版 ISV 应用密钥（api_applications 表，明文比对）

环境变量：
  TX_AUTH_ENABLED  — 设为 "false" 时跳过验证
"""

import os

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
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self._auth_enabled = os.getenv("TX_AUTH_ENABLED", "true").lower() != "false"

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return await call_next(request)

        if not self._auth_enabled:
            request.state.auth_method = "api_key"
            request.state.api_key_app_id = "dev-app-mock"
            request.state.api_key_scopes = ["*"]
            request.state.api_key_rate_limit = 1000
            if not getattr(request.state, "tenant_id", None):
                request.state.tenant_id = "a0000000-0000-0000-0000-000000000001"
            return await call_next(request)

        # 新版密钥: tx_xxx (SHA-256, api_keys 表)
        if api_key.startswith("tx_"):
            app_info = await self._verify_new_api_key(api_key)
        # 旧版密钥: txapp_ / txat_ (明文, api_applications 表)
        elif api_key.startswith(("txapp_", "txat_")):
            app_info = await self._verify_legacy_api_key(api_key)
        else:
            logger.warning("api_key_invalid_format", key_prefix=api_key[:10])
            return _error_response(401, "INVALID_API_KEY", "API Key format is invalid")

        if app_info is None:
            logger.warning(
                "api_key_verification_failed",
                key_prefix=api_key[:10],
                path=request.url.path,
            )
            return _error_response(401, "INVALID_API_KEY", "API Key is invalid or revoked")

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

    async def _verify_new_api_key(self, api_key: str) -> dict | None:
        """验证新版 API Key（tx_ 前缀，SHA-256 哈希，api_keys 表）。"""
        try:
            from shared.ontology.src.database import async_session_factory
        except ImportError:
            logger.warning("api_key_db_not_available", degraded=True)
            return None

        try:
            from sqlalchemy import text

            from shared.apikeys.src.key_generator import hash_api_key, validate_key_format

            if not validate_key_format(api_key):
                return None

            key_hash = hash_api_key(api_key)

            async with async_session_factory() as session:
                result = await session.execute(
                    text("""
                        SELECT id::text, tenant_id::text, name, permissions,
                               rate_limit_rps, status
                        FROM api_keys
                        WHERE key_hash = :key_hash AND is_deleted = FALSE
                        LIMIT 1
                    """),
                    {"key_hash": key_hash},
                )
                row = result.mappings().first()

                if not row:
                    return None

                if row["status"] != "active":
                    return None

                # 更新 last_used_at
                await session.execute(
                    text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :id"),
                    {"id": row["id"]},
                )
                await session.commit()

                return {
                    "app_id": row["id"],
                    "tenant_id": row["tenant_id"],
                    "app_name": row["name"],
                    "scopes": row["permissions"] if isinstance(row["permissions"], list) else [],
                    "rate_limit_per_min": (row["rate_limit_rps"] or 10) * 60,
                }
        except Exception as exc:
            logger.warning("api_key_verify_error", error=str(exc))
            return None

    async def _verify_legacy_api_key(self, api_key: str) -> dict | None:
        """验证旧版 API Key（txapp_/txat_ 前缀，api_applications 表）。"""
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
        except ConnectionError as exc:
            logger.warning("api_key_db_connection_error", error=str(exc))
            return None
        except OSError as exc:
            logger.warning("api_key_db_os_error", error=str(exc))
            return None
