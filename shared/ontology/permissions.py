"""权限矩阵定义

Resource类型对应 API 路径前缀或功能域。
Action: read / create / update / delete / export / approve

关键互斥规则：
  - AUDIT_ADMIN 只能 read:audit_logs，不能访问任何业务资源
  - SYSTEM_ADMIN 不能 read:audit_logs（三权分立核心约束）
  - CASHIER 只能操作 orders（下单/支付），不能访问 finance/analytics
"""
from enum import Enum

from .roles import PlatformRole, TenantRole


class Resource(str, Enum):
    AUDIT_LOGS = "audit_logs"
    USERS = "users"
    SYSTEM_CONFIG = "system_config"
    SECURITY_POLICY = "security_policy"
    # 业务资源
    ORDERS = "orders"
    MEMBERS = "members"
    MENU = "menu"
    FINANCE = "finance"
    ANALYTICS = "analytics"
    EMPLOYEES = "employees"
    SUPPLY = "supply"
    AGENT_CONFIG = "agent_config"


class Action(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    APPROVE = "approve"


# 权限元组类型：(Resource, Action)
Permission = tuple[Resource, Action]

# 角色权限矩阵
ROLE_PERMISSIONS: dict[PlatformRole | TenantRole, set[Permission]] = {
    # ── 平台级三权分立 ──────────────────────────────────────────
    PlatformRole.SYSTEM_ADMIN: {
        (Resource.USERS, Action.READ),
        (Resource.USERS, Action.CREATE),
        (Resource.USERS, Action.UPDATE),
        (Resource.USERS, Action.DELETE),
        (Resource.SYSTEM_CONFIG, Action.READ),
        (Resource.SYSTEM_CONFIG, Action.UPDATE),
        # 注意：【无】 AUDIT_LOGS 权限
    },
    PlatformRole.AUDIT_ADMIN: {
        (Resource.AUDIT_LOGS, Action.READ),
        (Resource.AUDIT_LOGS, Action.EXPORT),
        # 仅此两个权限，不能访问任何业务资源
    },
    PlatformRole.SECURITY_ADMIN: {
        (Resource.SECURITY_POLICY, Action.READ),
        (Resource.SECURITY_POLICY, Action.UPDATE),
        (Resource.SYSTEM_CONFIG, Action.READ),
        # 不能访问 orders/members/finance 等业务数据
    },
    # ── 租户业务角色 ────────────────────────────────────────────
    TenantRole.TENANT_OWNER: {
        (r, a)
        for r in [
            Resource.ORDERS,
            Resource.MEMBERS,
            Resource.MENU,
            Resource.FINANCE,
            Resource.ANALYTICS,
            Resource.EMPLOYEES,
            Resource.SUPPLY,
            Resource.AGENT_CONFIG,
        ]
        for a in Action
    },
    TenantRole.TENANT_ADMIN: {
        (Resource.ORDERS, Action.READ),
        (Resource.ORDERS, Action.CREATE),
        (Resource.ORDERS, Action.UPDATE),
        (Resource.MEMBERS, Action.READ),
        (Resource.MEMBERS, Action.UPDATE),
        (Resource.MENU, Action.READ),
        (Resource.MENU, Action.CREATE),
        (Resource.MENU, Action.UPDATE),
        (Resource.EMPLOYEES, Action.READ),
        (Resource.EMPLOYEES, Action.CREATE),
        (Resource.EMPLOYEES, Action.UPDATE),
        (Resource.ANALYTICS, Action.READ),
        (Resource.FINANCE, Action.READ),
    },
    TenantRole.BRAND_MANAGER: {
        (Resource.ORDERS, Action.READ),
        (Resource.MENU, Action.READ),
        (Resource.MENU, Action.CREATE),
        (Resource.MENU, Action.UPDATE),
        (Resource.ANALYTICS, Action.READ),
        (Resource.EMPLOYEES, Action.READ),
        (Resource.SUPPLY, Action.READ),
    },
    TenantRole.STORE_MANAGER: {
        (Resource.ORDERS, Action.READ),
        (Resource.ORDERS, Action.UPDATE),
        (Resource.ORDERS, Action.APPROVE),
        (Resource.MEMBERS, Action.READ),
        (Resource.MENU, Action.READ),
        (Resource.MENU, Action.UPDATE),
        (Resource.EMPLOYEES, Action.READ),
        (Resource.EMPLOYEES, Action.UPDATE),
        (Resource.ANALYTICS, Action.READ),
        (Resource.SUPPLY, Action.READ),
        (Resource.SUPPLY, Action.CREATE),
    },
    TenantRole.CASHIER: {
        (Resource.ORDERS, Action.READ),
        (Resource.ORDERS, Action.CREATE),
        (Resource.ORDERS, Action.UPDATE),
        (Resource.MEMBERS, Action.READ),   # 查询会员积分
        (Resource.MENU, Action.READ),
    },
    TenantRole.WAITER: {
        (Resource.ORDERS, Action.READ),
        (Resource.ORDERS, Action.CREATE),
        (Resource.MENU, Action.READ),
    },
    TenantRole.CHEF: {
        (Resource.ORDERS, Action.READ),
        (Resource.MENU, Action.READ),
        (Resource.SUPPLY, Action.READ),
    },
    TenantRole.SUPPLY_MANAGER: {
        (Resource.SUPPLY, Action.READ),
        (Resource.SUPPLY, Action.CREATE),
        (Resource.SUPPLY, Action.UPDATE),
        (Resource.SUPPLY, Action.APPROVE),
        (Resource.MENU, Action.READ),
    },
    TenantRole.FINANCE_STAFF: {
        (Resource.FINANCE, Action.READ),
        (Resource.FINANCE, Action.CREATE),
        (Resource.FINANCE, Action.UPDATE),
        (Resource.ORDERS, Action.READ),
        (Resource.ANALYTICS, Action.READ),
    },
    TenantRole.AUDITOR: {
        (Resource.ORDERS, Action.READ),
        (Resource.FINANCE, Action.READ),
        (Resource.ANALYTICS, Action.READ),
        (Resource.AUDIT_LOGS, Action.READ),  # 租户内审计日志
    },
    TenantRole.READONLY: {
        (Resource.ORDERS, Action.READ),
        (Resource.MENU, Action.READ),
        (Resource.ANALYTICS, Action.READ),
    },
}


def has_permission(role: str, resource: Resource, action: Action) -> bool:
    """检查角色是否有某权限"""
    try:
        r: PlatformRole | TenantRole = PlatformRole(role)
    except ValueError:
        try:
            r = TenantRole(role)
        except ValueError:
            return False
    return (resource, action) in ROLE_PERMISSIONS.get(r, set())
