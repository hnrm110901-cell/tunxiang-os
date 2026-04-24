"""
shared/config_templates — 屯象OS 业态模板包（L1 层）

提供 5 种开箱即用的餐厅业态配置模板：
  正餐 | 火锅 | 快餐 | 宴席 | 茶饮/咖啡

每种模板预置约 80% 的门店配置项，配合 DeliveryAgent（L2）20 问会话
和 Agent 动态策略（L3），三层合力将 1000+ 配置项简化为 20 个关键决策。

Usage:
    from shared.config_templates import get_template, RestaurantType

    tpl = get_template(RestaurantType.CASUAL_DINING)
    config_pkg = tpl.apply(answers)   # answers 来自 DeliveryAgent 20 问
"""

from .base import (
    AgentPolicySet,
    BaseTemplate,
    BillingRuleSet,
    DiscountPolicy,
    KDSZoneConfig,
    MemberTierConfig,
    PrinterConfig,
    RestaurantType,
    ShiftConfig,
    TenantConfigPackage,
)
from .registry import get_template, list_templates

__all__ = [
    "RestaurantType",
    "BaseTemplate",
    "PrinterConfig",
    "KDSZoneConfig",
    "ShiftConfig",
    "BillingRuleSet",
    "DiscountPolicy",
    "MemberTierConfig",
    "AgentPolicySet",
    "TenantConfigPackage",
    "get_template",
    "list_templates",
]
