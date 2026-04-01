"""L2 专业 Agent — 8 个场景化专业 Agent

与 agents/skills/ 中的 9 个 Skill Agent 互补：
- skills/: 偏后台分析（折扣守护、智能排菜、财务稽核等）
- specialists/: 偏前台运营（迎宾预订、等位桌台、点单服务等）

两套 Agent 共享同一个 Tool 网关和约束校验系统。
"""
from .base_specialist import SpecialistAgent, SpecialistResult
from .reception import ReceptionAgent
from .waitlist_table import WaitlistTableAgent
from .ordering import OrderingAgent
from .kitchen import KitchenAgent
from .member_growth import MemberGrowthAgent
from .checkout_risk import CheckoutRiskAgent
from .store_ops import StoreOpsAgent
from .hq_analytics import HQAnalyticsAgent

ALL_SPECIALISTS: list[type[SpecialistAgent]] = [
    ReceptionAgent,
    WaitlistTableAgent,
    OrderingAgent,
    KitchenAgent,
    MemberGrowthAgent,
    CheckoutRiskAgent,
    StoreOpsAgent,
    HQAnalyticsAgent,
]
