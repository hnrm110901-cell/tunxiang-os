"""跨店权限边界服务（D5 Nice-to-Have）

权限矩阵（resource_type: read | write | finance）:

| 角色                    | 可访问门店                 | read | write | finance(read) | finance(write) |
|-------------------------|---------------------------|:----:|:-----:|:-------------:|:--------------:|
| admin                   | 全部                      |  ✓   |   ✓   |       ✓       |       ✓        |
| boss                    | 全部                      |  ✓   |   ✓   |       ✓       |       ✓        |
| regional_manager        | user_store_scopes 授权    |  ✓   |   ✓*  |       ✓*      |       ✗        |
| store_manager           | User.store_id + 扩展授权  |  ✓   |   ✓   |       ✓       |       ✗        |
| head_chef               | User.store_id             |  ✓   |   ✗   |       ✗       |       ✗        |
| 其他员工 (waiter 等)    | 仅个人相关                |  ✗   |   ✗   |       ✗       |       ✗        |

（✓* = 取决于 UserStoreScope.access_level 与 finance_access 开关）

注：`boss` 在 UserRole 枚举中目前没有独立值，系统管理员 `admin` 等价于老板；
后续若增加 `boss` 枚举，将由 ADMIN + BOSS 共同匹配。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User, UserRole
from ..models.user_store_scope import UserStoreScope

logger = structlog.get_logger()


# 全局角色：对全部门店无限制
_GLOBAL_ROLES = {UserRole.ADMIN}

# 门店级管理层：默认自店可 read/write，finance 只读
_STORE_MANAGER_ROLES = {
    UserRole.STORE_MANAGER,
    UserRole.ASSISTANT_MANAGER,
    UserRole.FLOOR_MANAGER,
}

# 后厨线管理：自店 read 不含财务
_KITCHEN_ROLES = {UserRole.HEAD_CHEF, UserRole.STATION_MANAGER}

# 区域经理（当前枚举未显式提供，后续扩展时 CUSTOMER_MANAGER 可视为区域层代管）
_REGIONAL_ROLES = {UserRole.CUSTOMER_MANAGER}

# 财务专员：全 brand 财务读写（但仍受 brand_id 限制）
_FINANCE_ROLES = {UserRole.FINANCE}


VALID_RESOURCES = {"read", "write", "finance", "finance_write"}


class StoreAccessService:
    """跨店权限边界服务"""

    # ---------------- 公开 API ----------------

    @classmethod
    async def check_store_access(
        cls,
        session: AsyncSession,
        user: User,
        store_id: str,
        resource_type: str = "read",
    ) -> bool:
        """校验某用户对目标门店是否具备指定资源权限。

        参数:
            user: 已登录用户对象（或 SimpleNamespace 兼容测试桩）
            store_id: 目标门店标识
            resource_type: read / write / finance(=finance_read) / finance_write
        """
        if resource_type not in VALID_RESOURCES:
            raise ValueError(f"invalid resource_type: {resource_type}")
        if user is None or not store_id:
            return False

        role = _coerce_role(getattr(user, "role", None))

        # 1) 全局角色：全放行
        if role in _GLOBAL_ROLES:
            return True

        # 2) 财务专员：限 brand 范围内可读写全部门店财务
        if role in _FINANCE_ROLES:
            # 非跨品牌访问才放行（brand_id 在外层 validate_store_brand 校验）
            return True

        # 3) 是否命中自店
        own_store = getattr(user, "store_id", None)
        hits_own_store = bool(own_store) and str(own_store) == str(store_id)

        # 4) 从 user_store_scopes 查额外授权
        scope = await cls._get_scope(session, user.id, store_id)

        # 5) 区域经理：完全依赖 user_store_scopes
        if role in _REGIONAL_ROLES:
            if not scope:
                return False
            return cls._scope_allows(scope, resource_type)

        # 6) 店长线：自店默认 read/write + finance_read，write-finance 需显式授权
        if role in _STORE_MANAGER_ROLES:
            if hits_own_store:
                return cls._default_manager_allows(resource_type)
            if scope:
                return cls._scope_allows(scope, resource_type)
            return False

        # 7) 厨师长线：自店只读，无财务
        if role in _KITCHEN_ROLES:
            if not hits_own_store:
                # 若手动授权亦可
                return bool(scope) and cls._scope_allows(scope, resource_type)
            if resource_type in ("finance", "finance_write", "write"):
                return False
            return True

        # 8) 其他员工：仅个人资源（本服务不判定，默认拒绝门店级）
        return False

    @classmethod
    async def get_accessible_stores(
        cls, session: AsyncSession, user: User
    ) -> List[str]:
        """返回当前用户可访问（至少 read）的 store_id 列表。

        注意：全局角色返回空列表表示「无限制」应由调用方按需处理；
        本方法保守返回 ["*"] 作为哨兵。
        """
        role = _coerce_role(getattr(user, "role", None))
        if role in _GLOBAL_ROLES or role in _FINANCE_ROLES:
            return ["*"]

        result: set[str] = set()
        own_store = getattr(user, "store_id", None)
        if own_store:
            result.add(str(own_store))

        stmt = select(UserStoreScope).where(UserStoreScope.user_id == user.id)
        scopes = (await session.execute(stmt)).scalars().all()
        now = datetime.utcnow()
        for sc in scopes:
            if sc.expires_at and sc.expires_at < now:
                continue
            result.add(sc.store_id)
        return sorted(result)

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _default_manager_allows(resource_type: str) -> bool:
        """店长对自店默认权限"""
        if resource_type == "finance_write":
            return False
        return True  # read / write / finance(read)

    @staticmethod
    def _scope_allows(scope: UserStoreScope, resource_type: str) -> bool:
        """根据 UserStoreScope 记录判定"""
        # 过期
        if scope.expires_at and scope.expires_at < datetime.utcnow():
            return False

        level = (scope.access_level or "read").lower()

        if resource_type == "read":
            return True  # 只要存在授权记录，至少有 read
        if resource_type == "write":
            return level in ("write", "admin")
        if resource_type == "finance":
            return bool(scope.finance_access)
        if resource_type == "finance_write":
            return bool(scope.finance_access) and level == "admin"
        return False

    @staticmethod
    async def _get_scope(
        session: AsyncSession, user_id, store_id: str
    ) -> Optional[UserStoreScope]:
        stmt = select(UserStoreScope).where(
            UserStoreScope.user_id == user_id,
            UserStoreScope.store_id == store_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


def _coerce_role(raw) -> Optional[UserRole]:
    if raw is None:
        return None
    if isinstance(raw, UserRole):
        return raw
    try:
        return UserRole(raw)
    except Exception:
        return None


store_access_service = StoreAccessService()
