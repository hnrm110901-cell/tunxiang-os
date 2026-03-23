"""行业模板引擎 — Pro/Standard/Lite 三套配置

根据客户业态自动适配功能范围：
- Pro：高复杂直营正餐（徐记海鲜）— 全功能
- Standard：标准中式正餐连锁 — 80% 功能
- Lite：精品小店 — 核心收银 + 基础分析

决策4（菜单配置引擎）的上层：模板决定哪些域可用，菜单引擎按域裁剪菜单。
"""
from dataclasses import dataclass, field


@dataclass
class IndustryTemplate:
    """行业模板"""
    id: str
    name: str
    description: str
    enabled_domains: list[str]
    max_stores: int
    max_employees_per_store: int
    features: dict[str, bool]
    agent_tier: str  # full / standard / basic
    hardware: dict[str, bool]
    pricing_monthly_fen: int


# ─── 三套模板定义 ───

TEMPLATES = {
    "pro": IndustryTemplate(
        id="pro",
        name="海鲜酒楼 Pro",
        description="高复杂直营正餐集团（≥10家，有称重/活鲜/包厢/宴请/复杂供应链）",
        enabled_domains=["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent", "tx-ops"],
        max_stores=100,
        max_employees_per_store=80,
        features={
            "weight_pricing": True,       # 称重时价
            "banquet_management": True,    # 宴会管理
            "corporate_account": True,     # 企业挂账
            "multi_kitchen_station": True, # 多档口KDS
            "live_seafood_tank": True,     # 活鲜池管理
            "cross_store_analytics": True, # 跨店分析
            "agent_full_suite": True,      # 全部9个Agent
            "federated_learning": True,    # 跨店联邦学习
            "custom_report": True,         # 自定义报表
            "api_integration": True,       # 开放API
            "ipad_upgrade": True,          # iPad升级包
        },
        agent_tier="full",
        hardware={"android_pos": True, "mac_mini": True, "kds_tablet": True, "ipad": True},
        pricing_monthly_fen=700000,  # ¥7000/月
    ),

    "standard": IndustryTemplate(
        id="standard",
        name="中式连锁标准版",
        description="标准中式正餐连锁（5-30家），模板化交付",
        enabled_domains=["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent"],
        max_stores=30,
        max_employees_per_store=40,
        features={
            "weight_pricing": False,
            "banquet_management": False,
            "corporate_account": False,
            "multi_kitchen_station": True,
            "live_seafood_tank": False,
            "cross_store_analytics": True,
            "agent_full_suite": False,     # 6个核心Agent（守门员+优化型）
            "federated_learning": False,
            "custom_report": False,
            "api_integration": False,
            "ipad_upgrade": False,
        },
        agent_tier="standard",
        hardware={"android_pos": True, "mac_mini": True, "kds_tablet": True, "ipad": False},
        pricing_monthly_fen=500000,  # ¥5000/月
    ),

    "lite": IndustryTemplate(
        id="lite",
        name="精品小店 Lite",
        description="精品小店（1-10家），核心收银+基础分析",
        enabled_domains=["tx-trade", "tx-menu", "tx-supply", "tx-analytics"],
        max_stores=10,
        max_employees_per_store=15,
        features={
            "weight_pricing": False,
            "banquet_management": False,
            "corporate_account": False,
            "multi_kitchen_station": False,
            "live_seafood_tank": False,
            "cross_store_analytics": False,
            "agent_full_suite": False,     # 3个基础Agent（折扣守护+库存+排菜）
            "federated_learning": False,
            "custom_report": False,
            "api_integration": False,
            "ipad_upgrade": False,
        },
        agent_tier="basic",
        hardware={"android_pos": True, "mac_mini": False, "kds_tablet": True, "ipad": False},
        pricing_monthly_fen=300000,  # ¥3000/月
    ),
}


def get_template(template_id: str) -> IndustryTemplate | None:
    return TEMPLATES.get(template_id)


def get_enabled_agents(agent_tier: str) -> list[str]:
    """根据 Agent 层级返回可用 Agent 列表"""
    tiers = {
        "full": ["discount_guard", "smart_menu", "serve_dispatch", "member_insight",
                 "inventory_alert", "finance_audit", "store_inspect", "smart_service", "private_ops"],
        "standard": ["discount_guard", "smart_menu", "serve_dispatch",
                     "inventory_alert", "finance_audit", "member_insight"],
        "basic": ["discount_guard", "smart_menu", "inventory_alert"],
    }
    return tiers.get(agent_tier, tiers["basic"])


def compare_templates() -> list[dict]:
    """模板对比表（商务用）"""
    result = []
    for tid in ["lite", "standard", "pro"]:
        t = TEMPLATES[tid]
        result.append({
            "id": t.id,
            "name": t.name,
            "price_yuan": t.pricing_monthly_fen / 100,
            "domains": len(t.enabled_domains),
            "agents": len(get_enabled_agents(t.agent_tier)),
            "max_stores": t.max_stores,
            "features_count": sum(1 for v in t.features.values() if v),
            "hardware": t.hardware,
        })
    return result
