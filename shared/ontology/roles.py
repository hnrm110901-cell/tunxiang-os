"""屯象OS RBAC角色体系

等保三级三权分立：
  system_admin   — 管理用户和配置，【禁止】查看审计日志
  audit_admin    — 只读审计日志，【禁止】修改任何配置
  security_admin — 管理安全策略，【禁止】操作业务数据

互斥约束：同一账号不能同时持有上述三个角色中的任意两个。
"""
from enum import Enum


class PlatformRole(str, Enum):
    SYSTEM_ADMIN = "system_admin"
    AUDIT_ADMIN = "audit_admin"
    SECURITY_ADMIN = "security_admin"
    PLATFORM_SUPPORT = "platform_support"


class TenantRole(str, Enum):
    TENANT_OWNER = "tenant_owner"
    TENANT_ADMIN = "tenant_admin"
    BRAND_MANAGER = "brand_manager"
    STORE_MANAGER = "store_manager"
    CASHIER = "cashier"
    WAITER = "waiter"
    CHEF = "chef"
    SUPPLY_MANAGER = "supply_manager"
    FINANCE_STAFF = "finance_staff"
    AUDITOR = "auditor"       # 租户内审计员（只读）
    READONLY = "readonly"


# 三权分立互斥组（同一人不能同时持有）
MUTUALLY_EXCLUSIVE_ROLES: frozenset[PlatformRole] = frozenset({
    PlatformRole.SYSTEM_ADMIN,
    PlatformRole.AUDIT_ADMIN,
    PlatformRole.SECURITY_ADMIN,
})
