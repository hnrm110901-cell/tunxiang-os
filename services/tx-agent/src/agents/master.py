"""Master Agent — 编排中心

职责：
1. 接收用户意图（自然语言或结构化请求）
2. 路由到对应 Skill Agent
3. 协调多 Agent 协同（如库存预警 → 排菜调整）
4. 双层推理路由：边缘(Core ML) vs 云端(Claude API)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .event_bus import AgentEvent
    from .orchestrator import OrchestratorResult

import structlog

from .base import AgentResult, SkillAgent
from .memory_bus import MemoryBus

logger = structlog.get_logger()


class MasterAgent:
    """Master Agent — 统一编排 9 个 Skill Agent"""

    def __init__(self, tenant_id: str, store_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.memory_bus = MemoryBus.get_instance()
        self._agents: dict[str, SkillAgent] = {}

    def register(self, agent: SkillAgent) -> None:
        """注册 Skill Agent"""
        self._agents[agent.agent_id] = agent
        logger.info("agent_registered", agent_id=agent.agent_id, name=agent.agent_name)

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
        - finance_*/cost_* → finance_audit (财务稽核)
        - inspect_*/quality_* → store_inspect (巡店质检)
        - service_*/complaint_* → smart_service (智能客服)
        - campaign_*/journey_* → private_ops (私域运营)
        """
        routing_map = {
            "discount": "discount_guard",
            "menu": "smart_menu",
            "dish": "smart_menu",
            "serve": "serve_dispatch",
            "kitchen": "serve_dispatch",
            "member": "member_insight",
            "rfm": "member_insight",
            "inventory": "inventory_alert",
            "stock": "inventory_alert",
            "finance": "finance_audit",
            "cost": "finance_audit",
            "inspect": "store_inspect",
            "quality": "store_inspect",
            "service": "smart_service",
            "complaint": "smart_service",
            "campaign": "private_ops",
            "journey": "private_ops",
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
