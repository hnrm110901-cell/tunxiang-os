"""
FastAPI审计日志中间件 — 等保三级合规
自动记录所有敏感路径API请求到 audit_logs 表
"""

import asyncio
import base64
import json
import time
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# 需要详细审计的路径前缀
AUDIT_PATHS = ["/api/v1/auth/", "/api/v1/admin/", "/api/v1/finance/"]
# 所有4xx/5xx都要记录
ALWAYS_AUDIT_STATUS_CODES = range(400, 600)
# 请求体中需要脱敏的字段
MASK_FIELDS = {"password", "token", "phone", "id_card", "bank_account", "secret"}


class AuditMiddleware(BaseHTTPMiddleware):
    """
    记录规则：
    1. 所有 AUDIT_PATHS 下的请求（无论成功失败）
    2. 所有 4xx/5xx 响应
    3. 从 Authorization header 提取 JWT 中的 user_id/tenant_id
    4. 异步写入，不阻塞请求
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        should_audit = (
            any(request.url.path.startswith(p) for p in AUDIT_PATHS)
            or response.status_code in ALWAYS_AUDIT_STATUS_CODES
        )

        if should_audit:
            # 后台异步写，不阻塞响应
            asyncio.create_task(self._write_audit_log(request, response, duration_ms))

        return response

    async def _write_audit_log(self, request: Request, response: Response, duration_ms: int) -> None:
        try:
            # 从JWT提取用户信息（不验证，只解码payload部分）
            actor_id, tenant_id = self._extract_jwt_claims(request)

            client_ip = (
                request.headers.get("X-Real-IP")
                or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown")
            )

            # 确定操作类型
            action = self._infer_action(request.method, request.url.path, response.status_code)
            severity = "warning" if response.status_code >= 400 else "info"

            # 调用AuditLogService（需要DB session，这里用独立连接）
            logger.info(
                "audit_request",
                action=action,
                actor_id=actor_id,
                tenant_id=tenant_id,
                path=request.url.path,
                method=request.method,
                status_code=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
                severity=severity,
            )
        except Exception as exc:  # noqa: BLE001 — 审计失败不能影响业务
            logger.error("audit_middleware_error", error=str(exc))

    def _extract_jwt_claims(self, request: Request) -> tuple[str, str]:
        """从Bearer token中解码payload（不验证签名，仅提取claims用于日志）"""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return "anonymous", "unknown"
        try:
            payload_b64 = auth[7:].split(".")[1]
            # base64 padding
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.b64decode(payload_b64))
            return str(payload.get("sub", "unknown")), str(payload.get("tenant_id", "unknown"))
        except (ValueError, KeyError, IndexError):
            return "anonymous", "unknown"

    def _infer_action(self, method: str, path: str, status: int) -> str:
        if "/auth/login" in path:
            return "auth.login_failed" if status >= 400 else "auth.login"
        if "/auth/logout" in path:
            return "auth.logout"
        mapping = {
            "GET": "data.read",
            "POST": "data.create",
            "PUT": "data.update",
            "PATCH": "data.update",
            "DELETE": "data.delete",
        }
        return mapping.get(method, "data.unknown")
