"""tx-trade 内部 RBAC 依赖 — Sprint A4

用法：
    from src.security.rbac import require_role, require_mfa, UserContext

    @router.post("/refund")
    async def api_refund(
        body: RefundReq,
        request: Request,
        user: UserContext = Depends(require_role("store_manager", "admin")),
    ):
        ...

语义（与 gateway/src/middleware/rbac.py 对齐）：
    - 未认证（request.state.user_id 为空）→ 401 AUTH_MISSING
    - role 不在允许集合 → 403 ROLE_FORBIDDEN
    - require_mfa 且 request.state.mfa_verified 为 False → 403 MFA_REQUIRED

依赖链：
    gateway/AuthMiddleware 已将 JWT claims 注入 request.state（user_id /
    tenant_id / role / mfa_verified）。本装饰器直接读 state，不重复解 JWT，
    同一请求同一份用户上下文。

开发/测试模式：
    环境变量 TX_AUTH_ENABLED=false 时注入 mock UserContext（dev-user-mock /
    admin 角色），与 gateway AuthMiddleware 的 dev_bypass 行为保持一致。
    现有 tx-trade 单元测试通过该变量跳过 JWT 验证。

所有决策通过 structlog 记录 rbac_denied / rbac_mfa_required，后续接入 SIEM。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UserContext:
    """从 request.state 提取的用户上下文快照。

    字段与 gateway AuthMiddleware 注入的 state 字段一一对应。
    client_ip 额外从 request.client.host 读取，供审计日志使用。
    """

    user_id: str
    tenant_id: str
    role: str
    mfa_verified: bool
    store_id: str | None
    client_ip: str | None


def extract_user_context(request: Request) -> UserContext:
    """从 request.state 提取 UserContext。

    gateway AuthMiddleware 在 JWT 验证通过后填充以下字段；
    未认证请求的 user_id 为 None / ""。
    """
    state = request.state
    client = getattr(request, "client", None)
    client_ip = getattr(client, "host", None) if client else None
    x_fwd = request.headers.get("X-Forwarded-For") if hasattr(request, "headers") else None
    if x_fwd:
        # X-Forwarded-For 取第一段（原始客户端）
        client_ip = x_fwd.split(",", 1)[0].strip() or client_ip

    return UserContext(
        user_id=getattr(state, "user_id", "") or "",
        tenant_id=getattr(state, "tenant_id", "") or "",
        role=getattr(state, "role", "") or "",
        mfa_verified=bool(getattr(state, "mfa_verified", False)),
        store_id=getattr(state, "store_id", None),
        client_ip=client_ip,
    )


def _dev_bypass() -> bool:
    """与 gateway AuthMiddleware 同语义：TX_AUTH_ENABLED=false 时跳过 RBAC。

    仅用于本地单元测试与开发环境，生产环境必须 true。
    """
    return os.getenv("TX_AUTH_ENABLED", "true").lower() == "false"


def _mock_user_context() -> UserContext:
    return UserContext(
        user_id="dev-user-mock",
        tenant_id="a0000000-0000-0000-0000-000000000001",
        role="admin",
        mfa_verified=True,
        store_id=None,
        client_ip="127.0.0.1",
    )


def require_role(*allowed_roles: str) -> Callable:
    """依赖工厂：要求当前用户角色在 allowed_roles 之内。

    401 AUTH_MISSING   — 无认证
    403 ROLE_FORBIDDEN — 角色不匹配
    """
    allowed = {r for r in allowed_roles if r}

    async def _dep(request: Request) -> UserContext:
        if _dev_bypass():
            return _mock_user_context()
        ctx = extract_user_context(request)
        if not ctx.user_id:
            logger.warning(
                "rbac_auth_missing",
                path=getattr(request.url, "path", ""),
                allowed=sorted(allowed),
            )
            raise HTTPException(status_code=401, detail="AUTH_MISSING")
        if ctx.role not in allowed:
            logger.warning(
                "rbac_denied",
                user_id=ctx.user_id,
                user_role=ctx.role,
                allowed=sorted(allowed),
                path=getattr(request.url, "path", ""),
            )
            raise HTTPException(status_code=403, detail="ROLE_FORBIDDEN")
        return ctx

    return _dep


def require_mfa(*allowed_roles: str) -> Callable:
    """依赖工厂：在 require_role 基础上叠加 MFA 校验。

    用于大额减免 / 退款等高风险写操作。
    未 MFA → 403 MFA_REQUIRED。
    """
    base = require_role(*allowed_roles)

    async def _dep(request: Request) -> UserContext:
        if _dev_bypass():
            return _mock_user_context()
        ctx = await base(request)
        if not ctx.mfa_verified:
            logger.warning(
                "rbac_mfa_required",
                user_id=ctx.user_id,
                user_role=ctx.role,
                path=getattr(request.url, "path", ""),
            )
            raise HTTPException(status_code=403, detail="MFA_REQUIRED")
        return ctx

    return _dep
