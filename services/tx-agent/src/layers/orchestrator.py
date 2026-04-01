"""L2 Agent 编排层 — 总控 Agent (Dispatcher)

职责：
1. 接收 L1 场景会话层解析的意图
2. 路由到对应专业 Agent
3. 协调多 Agent 协同（串行/并行）
4. 汇总结果返回给前端
5. 处理需确认的工具调用

与 agents/master.py 的关系：
- MasterAgent: 编排 9 个 Skill Agent（偏分析型后台任务）
- Dispatcher: 编排 8 个 Specialist Agent（偏交互型前台运营）
- 两者可共存，通过 intent 前缀区分路由目标
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from .scene_session import (
    IntentType,
    ParsedIntent,
    SceneSessionManager,
    SessionContext,
    UserRole,
)
from .specialists.base_specialist import SpecialistAgent, SpecialistResult
from .tool_gateway import ToolGateway

logger = structlog.get_logger()


class Dispatcher:
    """L2 总控 Agent — 编排 8 个专业 Agent

    工作流程：
    1. 接收用户输入 + SessionContext
    2. 通过 SceneSessionManager 解析意图
    3. 路由到目标 SpecialistAgent.handle()
    4. 返回 SpecialistResult（可能包含待确认的工具调用）
    """

    def __init__(
        self,
        session_manager: SceneSessionManager,
        tool_gateway: ToolGateway,
        model_router: Optional[Any] = None,
    ) -> None:
        self.session_manager = session_manager
        self.tool_gateway = tool_gateway
        self._router = model_router
        self._specialists: dict[str, SpecialistAgent] = {}

    def register(self, agent: SpecialistAgent) -> None:
        """注册专业 Agent"""
        self._specialists[agent.agent_id] = agent
        logger.info(
            "specialist_registered",
            agent_id=agent.agent_id,
            name=agent.agent_name,
        )

    def get_specialist(self, agent_id: str) -> Optional[SpecialistAgent]:
        return self._specialists.get(agent_id)

    def list_specialists(self) -> list[dict]:
        return [a.get_info() for a in self._specialists.values()]

    # ── 主入口：自然语言输入 ──────────────────────────────────────────────────

    async def process_input(
        self,
        text: str,
        context: SessionContext,
    ) -> SpecialistResult:
        """处理用户自然语言输入

        完整流程：
        L1(意图解析) → L2(路由) → L3(工具调用) → 结果
        """
        # L1: 意图解析
        intent = self.session_manager.parse_intent(text, context)

        # 低置信度时尝试 LLM 意图解析
        if intent.confidence < 0.5 and self._router:
            intent = await self.session_manager.parse_intent_with_llm(
                text, context, self._router,
            )

        # 记录对话
        context.add_turn("user", text)

        # L2: 路由到专业 Agent
        result = await self.dispatch(
            agent_id=intent.target_agent,
            action=intent.action,
            params={**intent.params, "raw_input": text},
            context=context,
        )

        # 记录回复
        context.add_turn("assistant", result.message)

        return result

    # ── 结构化调度 ────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        agent_id: str,
        action: str,
        params: dict,
        context: SessionContext,
    ) -> SpecialistResult:
        """路由到指定 Specialist Agent 执行"""
        agent = self._specialists.get(agent_id)
        if not agent:
            return SpecialistResult(
                success=False,
                agent_id=agent_id,
                action=action,
                error=f"Specialist Agent 未找到: {agent_id}",
                message=f"暂不支持该功能（{agent_id}）",
            )

        logger.info(
            "dispatching",
            agent_id=agent_id,
            action=action,
            session_id=context.session_id,
            role=context.user_role.value,
        )

        return await agent.handle(action, params, context)

    # ── 多 Agent 协同 ─────────────────────────────────────────────────────────

    async def multi_dispatch(
        self,
        tasks: list[dict],
        context: SessionContext,
    ) -> list[SpecialistResult]:
        """多 Agent 并行执行

        Args:
            tasks: [{"agent_id": "...", "action": "...", "params": {...}}, ...]
            context: 共享会话上下文
        """
        async def _run(task: dict) -> SpecialistResult:
            return await self.dispatch(
                task["agent_id"],
                task["action"],
                task.get("params", {}),
                context,
            )

        results = await asyncio.gather(
            *[_run(t) for t in tasks],
            return_exceptions=True,
        )

        return [
            r if isinstance(r, SpecialistResult)
            else SpecialistResult(
                success=False, agent_id="unknown", action="unknown",
                error=str(r), message=f"执行出错: {r}",
            )
            for r in results
        ]

    # ── 确认工具调用 ──────────────────────────────────────────────────────────

    async def confirm_tool_call(
        self,
        tool_name: str,
        params: dict,
        context: SessionContext,
    ) -> SpecialistResult:
        """用户确认后执行待确认的工具调用"""
        result = await self.tool_gateway.execute_confirmed_tool(
            tool_name=tool_name,
            params=params,
            tenant_id=context.tenant_id,
        )
        return SpecialistResult(
            success=result.success,
            agent_id="dispatcher",
            action=f"confirmed_{tool_name}",
            message="操作已执行" if result.success else f"执行失败: {result.error}",
            data=result.data,
        )

    # ── 系统上下文 ────────────────────────────────────────────────────────────

    def get_system_context(self) -> dict:
        """获取 Dispatcher 系统上下文"""
        return {
            "registered_specialists": len(self._specialists),
            "specialist_list": [
                {"id": a.agent_id, "name": a.agent_name, "priority": a.priority}
                for a in self._specialists.values()
            ],
        }


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def create_dispatcher(
    model_router: Optional[Any] = None,
) -> Dispatcher:
    """创建完整的 Dispatcher 实例（含所有专业 Agent）"""
    from .specialists import ALL_SPECIALISTS

    session_mgr = SceneSessionManager()
    gateway = ToolGateway()
    dispatcher = Dispatcher(session_mgr, gateway, model_router)

    for agent_cls in ALL_SPECIALISTS:
        agent = agent_cls(tool_gateway=gateway, model_router=model_router)
        dispatcher.register(agent)

    return dispatcher
