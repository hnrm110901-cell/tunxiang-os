"""增强版租户注入中间件 — JWT claims 优先，X-Tenant-ID 兜底

职责：
  - 从 JWT claims（由 AuthMiddleware 注入的 request.state.tenant_id）提取 tenant_id
  - 如果 JWT 中没有（如 API Key 场景），从 X-Tenant-ID header 提取
  - 验证 UUID 格式
  - 为后续 RLS 使用准备 tenant_id（注入 request.state）

注意：本中间件必须在 AuthMiddleware 之后执行（即在 main.py 中先添加）。
"""

import os
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

TENANT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/",
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


class TenantMiddleware(BaseHTTPMiddleware):
    """从 JWT claims 或 X-Tenant-ID header 提取 tenant_id。

    解析优先级：
      1. request.state.tenant_id（由 AuthMiddleware 从 JWT 解码注入）
      2. X-Tenant-ID header（API Key / 外部调用场景）
      3. 两者都没有 → 403（白名单路径除外）

    TX_AUTH_ENABLED=false 时，允许缺少 tenant_id 的白名单路径通过。
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self._auth_enabled = os.getenv("TX_AUTH_ENABLED", "true").lower() != "false"

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        path = request.url.path

        # 白名单路径免检
        if any(path.startswith(prefix) for prefix in TENANT_EXEMPT_PREFIXES):
            if not hasattr(request.state, "tenant_id") or request.state.tenant_id is None:
                request.state.tenant_id = None
            return await call_next(request)

        # 优先使用 AuthMiddleware 从 JWT 注入的 tenant_id
        jwt_tenant_id = getattr(request.state, "tenant_id", None)
        header_tenant_id = request.headers.get("X-Tenant-ID")

        # 确定最终 tenant_id
        tenant_id = jwt_tenant_id or header_tenant_id

        if not tenant_id:
            # 开发模式下给个默认值
            if not self._auth_enabled:
                request.state.tenant_id = "a0000000-0000-0000-0000-000000000001"
                return await call_next(request)

            logger.warning("missing_tenant_id", path=path, method=request.method)
            return _error_response(403, "MISSING_TENANT", "X-Tenant-ID header is required")

        # 验证 UUID 格式
        try:
            uuid.UUID(str(tenant_id))
        except ValueError:
            logger.warning("invalid_tenant_id", path=path, tenant_id=tenant_id)
            return _error_response(400, "INVALID_TENANT", "tenant_id must be a valid UUID")

        # 如果 header 和 JWT 中都有 tenant_id，优先 JWT（防止 header 篡改）
        if jwt_tenant_id and header_tenant_id and str(jwt_tenant_id) != str(header_tenant_id):
            logger.warning(
                "tenant_id_mismatch",
                jwt_tenant_id=str(jwt_tenant_id),
                header_tenant_id=header_tenant_id,
                path=path,
                resolution="using_jwt_tenant_id",
            )
            tenant_id = jwt_tenant_id

        request.state.tenant_id = str(tenant_id)

        logger.debug(
            "tenant_injected",
            tenant_id=request.state.tenant_id,
            source="jwt" if jwt_tenant_id else "header",
            path=path,
        )

        return await call_next(request)
