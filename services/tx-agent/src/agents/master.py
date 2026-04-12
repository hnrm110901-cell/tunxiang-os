"""Master Agent — 编排中心

职责：
1. 接收用户意图（自然语言或结构化请求）
2. 路由到对应 Skill Agent
3. 协调多 Agent 协同（如库存预警 → 排菜调整）
4. 双层推理路由：边缘(Core ML) vs 云端(Claude API)
5. 支持从 DB 动态加载已启用 Agent（按门店/品牌灰度）
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .event_bus import AgentEvent
    from .orchestrator import OrchestratorResult

import structlog

from .base import AgentResult, SkillAgent
from .memory_bus import MemoryBus

logger = structlog.get_logger()


def _build_agent_class_map() -> dict[str, type[SkillAgent]]:
    """延迟构建 agent_id → SkillAgent 子类映射，避免循环导入。

    仅在 load_from_registry 首次调用时执行一次。
    """
    from .skills.ai_marketing_orchestrator import AiMarketingOrchestratorAgent
    from .skills.ai_waiter import AIWaiterAgent
    from .skills.attendance_recovery import AttendanceRecoveryAgent
    from .skills.audit_trail import AuditTrailAgent
    from .skills.banquet_growth import BanquetGrowthAgent
    from .skills.billing_anomaly import BillingAnomalyAgent
    from .skills.cashier_audit import CashierAuditAgent
    from .skills.closing_agent import ClosingAgent
    from .skills.competitor_watch import CompetitorWatchAgent
    from .skills.compliance_alert import ComplianceAlertAgent
    from .skills.content_generation import ContentGenerationAgent
    from .skills.cost_diagnosis import CostDiagnosisAgent
    from .skills.discount_guard import DiscountGuardAgent
    from .skills.dormant_recall import DormantRecallAgent
    from .skills.enterprise_activation import EnterpriseActivationAgent
    from .skills.finance_audit import FinanceAuditAgent
    from .skills.growth_attribution import GrowthAttributionAgent
    from .skills.growth_coach import GrowthCoachAgent
    from .skills.high_value_member import HighValueMemberAgent
    from .skills.ingredient_radar import IngredientRadarAgent
    from .skills.intel_reporter import IntelReporterAgent
    from .skills.inventory_alert import InventoryAlertAgent
    from .skills.kitchen_overtime import KitchenOvertimeAgent
    from .skills.member_insight import MemberInsightAgent
    from .skills.menu_advisor import MenuAdvisorAgent
    from .skills.new_customer_convert import NewCustomerConvertAgent
    from .skills.new_product_scout import NewProductScoutAgent
    from .skills.off_peak_traffic import OffPeakTrafficAgent
    from .skills.personalization_agent import PersonalizationAgent
    from .skills.pilot_recommender import PilotRecommenderAgent
    from .skills.private_ops import PrivateOpsAgent
    from .skills.queue_seating import QueueSeatingAgent
    from .skills.referral_growth import ReferralGrowthAgent
    from .skills.review_insight import ReviewInsightAgent
    from .skills.review_summary import ReviewSummaryAgent
    from .skills.salary_advisor import SalaryAdvisorAgent
    from .skills.seasonal_campaign import SeasonalCampaignAgent
    from .skills.serve_dispatch import ServeDispatchAgent
    from .skills.smart_customer_service import SmartCustomerServiceAgent
    from .skills.smart_menu import SmartMenuAgent
    from .skills.smart_service import SmartServiceAgent
    from .skills.stockout_alert import StockoutAlertAgent
    from .skills.store_inspect import StoreInspectAgent
    from .skills.table_dispatch import TableDispatchAgent
    from .skills.trend_discovery import TrendDiscoveryAgent
    from .skills.turnover_risk import TurnoverRiskAgent
    from .skills.voice_order import VoiceOrderAgent
    from .skills.workforce_planner import WorkforcePlannerAgent

    return {
        # 原有 9 个核心 Agent
        "discount_guard": DiscountGuardAgent,
        "smart_menu": SmartMenuAgent,
        "serve_dispatch": ServeDispatchAgent,
        "member_insight": MemberInsightAgent,
        "inventory_alert": InventoryAlertAgent,
        "finance_audit": FinanceAuditAgent,
        "store_inspect": StoreInspectAgent,
        "smart_service": SmartServiceAgent,
        "private_ops": PrivateOpsAgent,
        # 增长 Agent (8 个)
        "new_customer_convert": NewCustomerConvertAgent,
        "dormant_recall": DormantRecallAgent,
        "banquet_growth": BanquetGrowthAgent,
        "seasonal_campaign": SeasonalCampaignAgent,
        "referral_growth": ReferralGrowthAgent,
        "high_value_member": HighValueMemberAgent,
        "off_peak_traffic": OffPeakTrafficAgent,
        "content_generation": ContentGenerationAgent,
        # 情报 Agent (8 个)
        "competitor_watch": CompetitorWatchAgent,
        "review_insight": ReviewInsightAgent,
        "trend_discovery": TrendDiscoveryAgent,
        "new_product_scout": NewProductScoutAgent,
        "ingredient_radar": IngredientRadarAgent,
        "menu_advisor": MenuAdvisorAgent,
        "pilot_recommender": PilotRecommenderAgent,
        "intel_reporter": IntelReporterAgent,
        # 语音 + AI 服务员
        "voice_order": VoiceOrderAgent,
        "ai_waiter": AIWaiterAgent,
        # HR Agent
        "compliance_alert": ComplianceAlertAgent,
        "salary_advisor": SalaryAdvisorAgent,
        # 千人千面
        "personalization": PersonalizationAgent,
        # 专项运营 Agent
        "queue_seating": QueueSeatingAgent,
        "kitchen_overtime": KitchenOvertimeAgent,
        "billing_anomaly": BillingAnomalyAgent,
        "closing_ops": ClosingAgent,
        # AI 营销编排
        "ai_marketing_orchestrator": AiMarketingOrchestratorAgent,
        # 成本核算
        "cost_diagnosis": CostDiagnosisAgent,
        # 额外 Agent（不在 ALL_SKILL_AGENTS 中但有完整实现）
        "growth_attribution": GrowthAttributionAgent,
        "growth_coach": GrowthCoachAgent,
        "cashier_audit": CashierAuditAgent,
        "attendance_recovery": AttendanceRecoveryAgent,
        "audit_trail": AuditTrailAgent,
        "enterprise_activation": EnterpriseActivationAgent,
        "review_summary": ReviewSummaryAgent,
        "smart_customer_service": SmartCustomerServiceAgent,
        "stockout_alert": StockoutAlertAgent,
        "table_dispatch": TableDispatchAgent,
        "turnover_risk": TurnoverRiskAgent,
        "workforce_planner": WorkforcePlannerAgent,
    }


# 模块级缓存，首次调用后不再重复导入
_AGENT_CLASS_MAP_CACHE: dict[str, type[SkillAgent]] | None = None


def _get_agent_class_map() -> dict[str, type[SkillAgent]]:
    global _AGENT_CLASS_MAP_CACHE
    if _AGENT_CLASS_MAP_CACHE is None:
        _AGENT_CLASS_MAP_CACHE = _build_agent_class_map()
    return _AGENT_CLASS_MAP_CACHE


class MasterAgent:
    """Master Agent — 统一编排 Skill Agent

    支持两种注册方式：
    1. 手动 register()（向后兼容）
    2. load_from_registry() 从 DB 动态加载（灰度/按门店启用）
    """

    def __init__(self, tenant_id: str, store_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.memory_bus = MemoryBus.get_instance()
        self._agents: dict[str, SkillAgent] = {}

    def register(self, agent: SkillAgent) -> None:
        """注册 Skill Agent"""
        self._agents[agent.agent_id] = agent
        logger.info("agent_registered", agent_id=agent.agent_id, name=agent.agent_name)

    async def load_from_registry(
        self,
        db: "AsyncSession",
        *,
        available_agents: dict[str, type[SkillAgent]] | None = None,
    ) -> list[str]:
        """从 DB 加载该门店已启用的 Agent 并注册

        流程：
        1. 查询 AgentDeployment 表，找到 scope_type='store' 且 scope_id=self.store_id 的启用部署
        2. 联查 AgentTemplate 获取 agent name
        3. 如果 available_agents 提供了名称->类的映射，则实例化并注册
        4. 否则用内建的 _get_agent_class_map() 映射
        5. 返回已加载的 agent_id 列表

        Args:
            db: AsyncSession
            available_agents: 可选的 {agent_name: AgentClass} 映射，覆盖内建映射

        Returns:
            已成功加载的 agent_id 列表
        """
        from sqlalchemy import select

        from ..models.agent_deployment import AgentDeployment
        from ..models.agent_template import AgentTemplate

        if not self.store_id:
            logger.warning("load_from_registry_no_store_id", tenant_id=self.tenant_id)
            return []

        # 查询该门店已启用的 Agent 部署
        stmt = (
            select(AgentTemplate.name, AgentDeployment.config_override, AgentDeployment.agent_level)
            .join(AgentTemplate, AgentDeployment.template_id == AgentTemplate.id)
            .where(
                AgentDeployment.scope_type == "store",
                AgentDeployment.scope_id == self.store_id,
                AgentDeployment.is_enabled.is_(True),
                AgentDeployment.is_deleted.is_(False),
                AgentTemplate.is_deleted.is_(False),
            )
        )
        result = await db.execute(stmt)
        rows = result.all()

        class_map = available_agents or _get_agent_class_map()
        loaded: list[str] = []

        for agent_name, config_override, agent_level in rows:
            agent_cls = class_map.get(agent_name)
            if agent_cls is None:
                logger.warning(
                    "agent_class_not_found",
                    agent_name=agent_name,
                    store_id=self.store_id,
                )
                continue

            agent = agent_cls(
                tenant_id=self.tenant_id,
                store_id=self.store_id,
                db=db,
            )
            if agent_level is not None:
                agent.agent_level = agent_level

            self.register(agent)
            loaded.append(agent.agent_id)
            logger.info(
                "agent_loaded_from_registry",
                agent_id=agent.agent_id,
                store_id=self.store_id,
                agent_level=agent_level,
            )

        logger.info(
            "load_from_registry_complete",
            store_id=self.store_id,
            loaded_count=len(loaded),
            loaded_agents=loaded,
        )
        return loaded

    def get_agent(self, agent_id: str) -> SkillAgent | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[dict]:
        """列出所有已注册 Agent"""
        return [a.get_info() for a in self._agents.values()]

    async def dispatch(self, agent_id: str, action: str, params: dict[str, Any]) -> AgentResult:
        """路由到指定 Skill Agent 执行"""
        agent = self._agents.get(agent_id)
        if not agent:
            return AgentResult(
                success=False,
                action=action,
                error=f"Agent not found: {agent_id}",
            )

        return await agent.run(action, params)

    async def route_intent(self, intent: str, params: dict[str, Any]) -> AgentResult:
        """基于意图自动路由到合适的 Agent

        意图路由映射：
        - discount_* → discount_guard (折扣守护)
        - menu_*/dish_* → smart_menu (智能排菜)
        - serve_*/kitchen_* → serve_dispatch (出餐调度)
        - member_*/rfm_* → member_insight (会员洞察)
        - inventory_*/stock_* → inventory_alert (库存预警)
        - finance_* → finance_audit (财务稽核)
        - cost_*/stocktake_*/break_even/contribution_*/scenario_*/dish_margin/price_trend_* → cost_diagnosis (成本核算)
        - inspect_*/quality_* → store_inspect (巡店质检)
        - service_*/complaint_* → smart_service (智能客服)
        - campaign_*/journey_* → private_ops (私域运营)
        """
        routing_map = {
            "discount": "discount_guard",
            "menu": "smart_menu",
            "dish": "smart_menu",
            "serve": "serve_dispatch",
            "member": "member_insight",
            "rfm": "member_insight",
            "inventory": "inventory_alert",
            "stock": "inventory_alert",
            "finance": "finance_audit",
            # 成本核算 Agent 接管所有成本类意图
            "cost": "cost_diagnosis",
            "stocktake": "cost_diagnosis",
            "break": "cost_diagnosis",      # break_even
            "contribution": "cost_diagnosis",
            "scenario": "cost_diagnosis",
            "price": "cost_diagnosis",      # price_trend_alert
            "channel": "cost_diagnosis",    # channel_cost_compare
            "inspect": "store_inspect",
            "quality": "store_inspect",
            "service": "smart_service",
            "complaint": "smart_service",
            "campaign": "private_ops",
            "journey": "private_ops",
            # 语音 + AI 服务员
            "voice": "voice_order",
            "ai_waiter": "ai_waiter",
            # 增长 Agent（精细路由）
            "growth": "growth_coach",
            "dormant": "dormant_recall",
            "banquet": "banquet_growth",
            "seasonal": "seasonal_campaign",
            "referral": "referral_growth",
            "convert": "new_customer_convert",
            "offpeak": "off_peak_traffic",
            # 情报 Agent（精细路由）
            "intel": "intel_reporter",
            "competitor": "competitor_watch",
            "review": "review_insight",
            "trend": "trend_discovery",
            "scout": "new_product_scout",
            "ingredient": "ingredient_radar",
            "advisor": "menu_advisor",
            "pilot": "pilot_recommender",
            # 千人千面
            "personalization": "personalization",
            "personalize": "personalization",
            # 专项运营 Agent
            "queue": "queue_seating",
            "seating": "queue_seating",
            "kitchen": "kitchen_overtime",
            "overtime": "kitchen_overtime",
            "billing": "billing_anomaly",
            "closing": "closing_ops",
            # HR Agent
            "compliance": "compliance_alert",
            "salary": "salary_advisor",
            "attendance": "attendance_recovery",
            "turnover": "turnover_risk",
            "workforce": "workforce_planner",
        }

        # 从 intent 前缀匹配 agent
        prefix = intent.split("_")[0] if "_" in intent else intent
        agent_id = routing_map.get(prefix)

        if not agent_id:
            return AgentResult(
                success=False,
                action=intent,
                error=f"No agent found for intent: {intent}",
            )

        return await self.dispatch(agent_id, intent, params)

    async def multi_agent_execute(
        self,
        tasks: list[dict],
    ) -> list[AgentResult]:
        """多 Agent 并行执行（协同场景）

        Args:
            tasks: [{"agent_id": "...", "action": "...", "params": {...}}, ...]

        Returns:
            对应的结果列表
        """
        import asyncio

        async def _run(task: dict) -> AgentResult:
            return await self.dispatch(
                task["agent_id"], task["action"], task.get("params", {})
            )

        results = await asyncio.gather(*[_run(t) for t in tasks], return_exceptions=True)

        return [
            r if isinstance(r, AgentResult) else AgentResult(success=False, action="unknown", error=str(r))
            for r in results
        ]

    async def orchestrate(
        self,
        trigger: "AgentEvent | str",
        context: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> "OrchestratorResult":
        """AI 驱动的多 Agent 编排（新入口，替代 route_intent 的关键词路由）

        tenant_id 参数优先于 self.tenant_id，允许事件消费者以真实租户身份
        发起编排，避免 master("system") 导致成本统计错误和日志混淆。

        与 route_intent / dispatch 向后兼容，不影响现有调用路径。
        """
        from .orchestrator import AgentOrchestrator
        effective_tenant = tenant_id or self.tenant_id
        orchestrator = AgentOrchestrator(
            master_agent=self,
            model_router=self._get_model_router(),
            tenant_id=effective_tenant,
            store_id=self.store_id,
        )
        return await orchestrator.orchestrate(trigger, context)

    def _get_model_router(self) -> Any:
        """获取 ModelRouter 实例（延迟导入避免循环依赖）"""
        from ..services.model_router import ModelRouter
        return ModelRouter()

    def get_system_context(self) -> dict:
        """获取系统上下文（供 LLM prompt 注入）"""
        return {
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "registered_agents": len(self._agents),
            "peer_findings": self.memory_bus.get_peer_context(
                exclude_agent="master",
                store_id=self.store_id,
            ),
        }
