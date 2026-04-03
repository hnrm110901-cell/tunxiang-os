"""菜单配置引擎 — 决策4

根据客户签约的产品域、角色权限、业态类型，动态生成菜单树。
新店联网后自动从云端拉取配置，不需人工配置。

数据结构：Module → Group → MenuItem → Permission
"""
from typing import Optional

from pydantic import BaseModel


class MenuItem(BaseModel):
    """菜单项"""
    id: str
    label: str
    icon: str
    path: str
    count: Optional[int] = None
    roles: list[str] = ["admin"]  # 可见角色列表
    requires_domain: Optional[str] = None  # 需要签约的产品域


class MenuGroup(BaseModel):
    """菜单分组"""
    label: str
    items: list[MenuItem]


class MenuModule(BaseModel):
    """一级模块（对应 IconRail 的一个图标）"""
    id: str
    icon: str
    label: str
    priority: int = 0  # 排序
    requires_domain: Optional[str] = None
    groups: list[MenuGroup]


class MenuConfig(BaseModel):
    """完整菜单配置"""
    tenant_id: str
    modules: list[MenuModule]


# ─── 默认菜单模板（全量） ───

DEFAULT_MODULES = [
    MenuModule(
        id="dashboard", icon="📊", label="驾驶舱", priority=0,
        groups=[MenuGroup(label="总览", items=[
            MenuItem(id="hq-dashboard", label="经营驾驶舱", icon="📊", path="/dashboard", roles=["admin", "manager"]),
            MenuItem(id="store-health", label="门店健康", icon="🏥", path="/store-health", roles=["admin", "manager"]),
            MenuItem(id="agent-monitor", label="Agent 监控", icon="🤖", path="/agents", roles=["admin"]),
        ])],
    ),
    MenuModule(
        id="trade", icon="💰", label="交易", priority=1, requires_domain="tx-trade",
        groups=[MenuGroup(label="交易管理", items=[
            MenuItem(id="orders", label="订单列表", icon="📋", path="/trade/orders", roles=["admin", "manager", "cashier"]),
            MenuItem(id="settlements", label="日结/班结", icon="📑", path="/trade/settlements", roles=["admin", "manager"]),
        ])],
    ),
    MenuModule(
        id="menu", icon="🍽️", label="菜品", priority=2, requires_domain="tx-menu",
        groups=[
            MenuGroup(label="菜品管理", items=[
                MenuItem(id="dish-list", label="菜品列表", icon="🍜", path="/menu/dishes", roles=["admin", "manager", "chef"]),
                MenuItem(id="bom", label="BOM 配方", icon="📐", path="/menu/bom", roles=["admin", "chef"]),
                MenuItem(id="ranking", label="菜单排名", icon="🏆", path="/menu/ranking", roles=["admin", "manager"]),
            ]),
        ],
    ),
    MenuModule(
        id="member", icon="👥", label="会员", priority=3, requires_domain="tx-member",
        groups=[MenuGroup(label="会员管理", items=[
            MenuItem(id="customers", label="会员列表", icon="👤", path="/member/customers", roles=["admin", "manager"]),
            MenuItem(id="rfm", label="RFM 分析", icon="📊", path="/member/rfm", roles=["admin"]),
            MenuItem(id="campaigns", label="营销活动", icon="🎯", path="/member/campaigns", roles=["admin", "manager"]),
        ])],
    ),
    MenuModule(
        id="supply", icon="📦", label="供应链", priority=4, requires_domain="tx-supply",
        groups=[MenuGroup(label="库存", items=[
            MenuItem(id="inventory", label="库存管理", icon="📦", path="/supply/inventory", roles=["admin", "manager", "chef"]),
            MenuItem(id="waste", label="损耗分析", icon="🗑️", path="/supply/waste", roles=["admin", "manager"]),
            MenuItem(id="suppliers", label="供应商", icon="🚚", path="/supply/suppliers", roles=["admin"]),
        ])],
    ),
    MenuModule(
        id="finance", icon="💹", label="财务", priority=5, requires_domain="tx-finance",
        groups=[MenuGroup(label="财务", items=[
            MenuItem(id="daily-profit", label="日利润", icon="💰", path="/finance/daily", roles=["admin", "manager"]),
            MenuItem(id="cost-rate", label="成本率", icon="📉", path="/finance/cost-rate", roles=["admin", "manager"]),
            MenuItem(id="monthly", label="月度报告", icon="📋", path="/finance/monthly", roles=["admin"]),
        ])],
    ),
    MenuModule(
        id="org", icon="🏢", label="组织", priority=6, requires_domain="tx-org",
        groups=[MenuGroup(label="人力", items=[
            MenuItem(id="employees", label="员工管理", icon="👥", path="/org/employees", roles=["admin", "manager"]),
            MenuItem(id="schedule", label="排班", icon="📅", path="/org/schedule", roles=["admin", "manager"]),
            MenuItem(id="attendance", label="考勤", icon="⏰", path="/org/attendance", roles=["admin", "manager"]),
        ])],
    ),
    MenuModule(
        id="analytics", icon="📈", label="分析", priority=7, requires_domain="tx-analytics",
        groups=[
            MenuGroup(label="分析", items=[
                MenuItem(id="kpi", label="KPI 监控", icon="🎯", path="/analytics/kpi", roles=["admin", "manager"]),
                MenuItem(id="decisions", label="AI 决策", icon="🧠", path="/analytics/decisions", roles=["admin", "manager"]),
            ]),
        ],
    ),
    MenuModule(
        id="agent", icon="🤖", label="Agent", priority=8,
        groups=[MenuGroup(label="Agent OS", items=[
            MenuItem(id="agent-list", label="Agent 列表", icon="🤖", path="/agent/list", roles=["admin"]),
            MenuItem(id="agent-config", label="配置", icon="⚙️", path="/agent/config", roles=["admin"]),
        ])],
    ),
]


def generate_menu_for_tenant(
    tenant_domains: list[str],
    user_role: str = "admin",
) -> list[dict]:
    """根据租户签约域 + 用户角色生成菜单

    Args:
        tenant_domains: 租户已签约的产品域列表 ["tx-trade", "tx-menu", ...]
        user_role: 当前用户角色 admin/manager/chef/waiter/cashier

    Returns:
        过滤后的菜单模块列表
    """
    result = []
    for module in DEFAULT_MODULES:
        # 域权限检查
        if module.requires_domain and module.requires_domain not in tenant_domains:
            continue

        # 角色过滤菜单项
        filtered_groups = []
        for group in module.groups:
            filtered_items = [item for item in group.items if user_role in item.roles]
            if filtered_items:
                filtered_groups.append({"label": group.label, "items": [item.model_dump() for item in filtered_items]})

        if filtered_groups:
            result.append({
                "id": module.id,
                "icon": module.icon,
                "label": module.label,
                "groups": filtered_groups,
            })

    return result
