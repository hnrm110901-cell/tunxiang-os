"""域级 RBAC 授权中间件 — Gateway 层二次鉴权

职责：
  - 根据请求路径中的 domain 段（/api/v1/{domain}/...）确定目标域
  - 检查当前用户角色是否有权访问该域
  - 对高危操作（分账/退款/结算/导出）强制校验 MFA
  - 有效防止普通角色（如收银员）访问敏感域（如 finance/pay/org）

角色-域映射关系遵循 shared/ontology/permissions.py 定义。
"""

from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# ── 域授权矩阵 ─────────────────────────────────────────────────────
# None = 该域对所有已认证用户开放（仅需 JWT/API Key 认证）
# set  = 仅允许指定角色访问

DOMAIN_ROLE_MAP: dict[str, Optional[set[str]]] = {
    # 敏感域 — 需显式授权
    "finance": {"tenant_owner", "tenant_admin", "finance_staff", "auditor"},
    "pay": {"tenant_owner", "tenant_admin", "store_manager", "cashier"},
    "org": {"tenant_owner", "tenant_admin", "store_manager"},
    "supply": {"tenant_owner", "tenant_admin", "supply_manager", "store_manager"},
    "civic": {"tenant_owner", "tenant_admin", "store_manager"},
    "agent": {"tenant_owner", "tenant_admin"},
    "agent-hub": {"tenant_owner", "tenant_admin"},
    "agent-monitor": {"tenant_owner", "tenant_admin"},
    "master-agent": {"tenant_owner", "tenant_admin"},
    "brain": {"tenant_owner", "tenant_admin"},
    "devforge": {"system_admin", "tenant_owner", "tenant_admin"},
    # 开放域 — 所有已认证用户可访问
    "trade": None,
    "menu": None,
    "member": None,
    "ops": None,
    "growth": None,
    "intel": None,
    "analytics": None,
    "kds": None,
    "print": None,
    "stream": None,
    "nlq": None,
    "anomaly": None,
    "dashboard": None,
    "narrative": None,
    "insights": None,
    "expense": None,
}

# ── 高危操作路径前缀（必须 MFA） ────────────────────────────────────
MFA_REQUIRED_PREFIXES: tuple[str, ...] = (
    "/api/v1/finance/splits/",
    "/api/v1/finance/refunds/",
    "/api/v1/finance/settlement/",
    "/api/v1/finance/invoices/export",
    "/api/v1/ops/daily-settlement/close",
    "/api/v1/analytics/export/",
    "/api/v1/member/export/",
    "/api/v1/supply/audit/",
    "/api/v1/org/salary/",
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


class DomainAuthzMiddleware(BaseHTTPMiddleware):
    """域级授权 + MFA 强制中间件。

    在 AuthMiddleware 认证之后执行（在 main.py 中注册于 AuthMiddleware 内层）。
    白名单路径（/health, /docs 等）及 auth 相关路径跳过检查。
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        path = request.url.path

        # 白名单路径跳过
        if _is_exempt(path):
            return await call_next(request)

        # 仅对 /api/v1/{domain}/ 路径执行域授权检查
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        # 提取 domain
        parts = path.split("/")
        if len(parts) < 4:
            return await call_next(request)
        domain = parts[3]

        # 未注册的域默认拒绝（单次查找）
        if domain not in DOMAIN_ROLE_MAP:
            logger.warning("domain_authz_unknown_domain", domain=domain, path=path)
            return _error_response(403, "DOMAIN_DENIED", f"Unknown domain: {domain}")

        allowed_roles = DOMAIN_ROLE_MAP[domain]

        # 开放域（None）不需角色检查，所有已认证用户可访问
        if allowed_roles is None:
            # 但仍需检查高危操作 MFA
            mfa_check = _check_mfa_required(request, path)
            if mfa_check:
                return mfa_check
            return await call_next(request)

        # 敏感域 — 检查角色
        role = getattr(request.state, "role", None)
        if not role or role not in allowed_roles:
            logger.warning(
                "domain_authz_denied",
                user_role=role,
                domain=domain,
                path=path,
                allowed_roles=sorted(allowed_roles),
            )
            return _error_response(
                403,
                "RBAC_DENIED",
                f"Role '{role}' is not allowed to access '{domain}' domain",
            )

        # 敏感域 + 高危操作检查 MFA
        mfa_check = _check_mfa_required(request, path)
        if mfa_check:
            return mfa_check

        return await call_next(request)


def _is_exempt(path: str) -> bool:
    """检查路径是否在免域授权白名单中。"""
    exempt_prefixes = (
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/auth/",
        "/api/v1/domains",
        "/api/v1/menu-config",
    )
    return any(path.startswith(prefix) for prefix in exempt_prefixes)


def _check_mfa_required(request: Request, path: str) -> Optional[JSONResponse]:
    """检查高危操作是否需要 MFA。

    Returns:
        JSONResponse (403) 如果 MFA 未验证；None 表示通过。
    """
    if not any(path.startswith(prefix) for prefix in MFA_REQUIRED_PREFIXES):
        return None

    mfa_verified = getattr(request.state, "mfa_verified", False)
    if not mfa_verified:
        logger.warning(
            "mfa_required",
            path=path,
            user_id=getattr(request.state, "user_id", None),
            role=getattr(request.state, "role", None),
        )
        return _error_response(403, "MFA_REQUIRED", "此操作需要完成双因素认证")

    return None
