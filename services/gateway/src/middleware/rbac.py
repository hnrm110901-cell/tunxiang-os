"""RBAC权限检查 — FastAPI依赖注入方式

使用方式：
    @router.get("/audit-logs")
    async def get_logs(
        _: None = Depends(require_roles(PlatformRole.AUDIT_ADMIN))
    ): ...

三权分立检查在每次角色授权时也执行（防止数据库出现违规状态）。
"""

from __future__ import annotations

from typing import Callable

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.ontology.permissions import Action, Resource, has_permission
from shared.ontology.roles import MUTUALLY_EXCLUSIVE_ROLES, PlatformRole, TenantRole

logger = structlog.get_logger(__name__)
security = HTTPBearer(auto_error=False)


class UserContext:
    """从JWT解码的用户上下文"""

    def __init__(
        self,
        user_id: str,
        tenant_id: str,
        role: str,
        mfa_verified: bool,
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role
        self.mfa_verified = mfa_verified


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserContext:
    """从Bearer JWT提取当前用户（依赖注入）"""
    if not credentials:
        raise HTTPException(status_code=401, detail="缺少认证token")

    # 动态导入避免循环依赖（JWTService在gateway服务中）
    try:
        from services.jwt_service import JWTService  # type: ignore[import]
    except ImportError:
        from jwt_service import JWTService  # type: ignore[import]

    try:
        payload = JWTService().verify_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="token格式无效") from exc

    if not payload:
        raise HTTPException(status_code=401, detail="token无效或已过期")

    return UserContext(
        user_id=payload.get("sub", ""),
        tenant_id=payload.get("tenant_id", ""),
        role=payload.get("role", ""),
        mfa_verified=payload.get("mfa_verified", False),
    )


def require_roles(*allowed_roles: PlatformRole | TenantRole) -> Callable:
    """路由级角色检查

    用法：
        @router.get("/some-path")
        async def handler(
            user: UserContext = Depends(require_roles(PlatformRole.AUDIT_ADMIN))
        ): ...
    """
    role_values = {r.value for r in allowed_roles}

    async def check(
        request: Request,
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        if user.role not in role_values:
            logger.warning(
                "rbac_denied",
                user_id=user.user_id,
                user_role=user.role,
                required_roles=sorted(role_values),
                path=request.url.path,
            )
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return check


def require_mfa() -> Callable:
    """要求MFA已验证（admin/ops角色的关键操作）

    用法：
        @router.delete("/users/{user_id}")
        async def delete_user(
            user: UserContext = Depends(require_mfa())
        ): ...
    """

    async def check(
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        if not user.mfa_verified:
            raise HTTPException(
                status_code=403,
                detail="此操作需要完成双因素认证",
            )
        return user

    return check


def require_permission(resource: Resource, action: Action) -> Callable:
    """细粒度权限检查

    用法：
        @router.get("/finance/reports")
        async def get_reports(
            user: UserContext = Depends(
                require_permission(Resource.FINANCE, Action.READ)
            )
        ): ...
    """

    async def check(
        request: Request,
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        if not has_permission(user.role, resource, action):
            logger.warning(
                "rbac_permission_denied",
                user_id=user.user_id,
                user_role=user.role,
                resource=resource.value,
                action=action.value,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=403,
                detail=f"缺少权限: {resource.value}:{action.value}",
            )
        return user

    return check


def check_separation_of_duties(roles: list[str]) -> bool:
    """检查角色列表是否违反三权分立互斥约束

    返回 True 表示合法（无冲突），False 表示违反约束。
    用于角色授权时的应用层校验。

    Args:
        roles: 待检查的角色值列表（str形式）

    Returns:
        True — 无互斥冲突
        False — 存在三权分立互斥冲突，必须拒绝
    """
    exclusive_values = {r.value for r in MUTUALLY_EXCLUSIVE_ROLES}
    held_exclusive = [r for r in roles if r in exclusive_values]
    return len(held_exclusive) <= 1
