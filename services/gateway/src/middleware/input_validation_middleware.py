"""输入验证中间件 -- OWASP Top 10 防护

对所有请求的 query params 和 JSON body 做基础安全扫描：
1. 检测 SQL 注入特征 -> 返回 400
2. 检测 XSS 攻击载荷 -> 返回 400
3. 字符串长度限制
4. 可疑请求记录审计日志

集成方式：在 FastAPI app 中添加中间件
    app.add_middleware(InputValidationMiddleware)
"""

import json
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shared.security.src.sql_guard import check_sql_injection
from shared.security.src.xss_guard import get_csp_header, validate_no_script

logger = structlog.get_logger(__name__)

# 不需要验证的路径前缀（健康检查等）
_SKIP_PATHS = frozenset({"/health", "/readiness", "/metrics"})

# 单个字段最大长度
_MAX_FIELD_LENGTH = 5000

# 请求体最大大小（10MB）
_MAX_BODY_SIZE = 10 * 1024 * 1024


class InputValidationMiddleware(BaseHTTPMiddleware):
    """请求输入安全验证中间件。"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 跳过健康检查等内部路径
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # ---- 1. 检查 query params ----
        violation = self._check_query_params(request)
        if violation:
            return self._reject(request, violation)

        # ---- 2. 检查 JSON body（仅 POST/PUT/PATCH） ----
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                violation = await self._check_json_body(request)
                if violation:
                    return self._reject(request, violation)

        # ---- 3. 正常放行，添加安全响应头 ----
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = get_csp_header()
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

    def _check_query_params(self, request: Request) -> str | None:
        """扫描 query params，返回违规描述或 None。"""
        for key, value in request.query_params.items():
            if len(value) > _MAX_FIELD_LENGTH:
                return f"query param '{key}' exceeds max length"
            if check_sql_injection(value):
                return f"SQL injection detected in query param '{key}'"
            try:
                validate_no_script(value)
            except ValueError:
                return f"XSS detected in query param '{key}'"
        return None

    async def _check_json_body(self, request: Request) -> str | None:
        """扫描 JSON body 中所有字符串值，返回违规描述或 None。"""
        try:
            # 检查 body 大小
            body = await request.body()
            if len(body) > _MAX_BODY_SIZE:
                return "request body exceeds size limit"
            if not body:
                return None
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "invalid JSON body"

        return self._scan_values(data, path="body")

    def _scan_values(self, data: object, path: str, depth: int = 0) -> str | None:
        """递归扫描 JSON 值中的字符串字段。"""
        if depth > 10:  # 防止嵌套过深的 DoS
            return f"JSON nesting too deep at '{path}'"

        if isinstance(data, str):
            if len(data) > _MAX_FIELD_LENGTH:
                return f"field '{path}' exceeds max length"
            if check_sql_injection(data):
                return f"SQL injection detected in '{path}'"
            try:
                validate_no_script(data)
            except ValueError:
                return f"XSS detected in '{path}'"
        elif isinstance(data, dict):
            for key, value in data.items():
                violation = self._scan_values(value, f"{path}.{key}", depth + 1)
                if violation:
                    return violation
        elif isinstance(data, list):
            for i, item in enumerate(data[:200]):  # 限制扫描数量
                violation = self._scan_values(item, f"{path}[{i}]", depth + 1)
                if violation:
                    return violation

        return None

    def _reject(self, request: Request, reason: str) -> JSONResponse:
        """拒绝请求并记录审计日志。"""
        client_ip = (
            request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        logger.warning(
            "input_validation_rejected",
            path=request.url.path,
            method=request.method,
            reason=reason,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent", ""),
        )
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "INPUT_VALIDATION_FAILED",
                    "message": "Request contains invalid or potentially malicious input.",
                },
            },
        )
