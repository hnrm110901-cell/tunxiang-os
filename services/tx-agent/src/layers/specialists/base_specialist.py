"""专业 Agent 基类 — 场景化前台运营 Agent

与 agents/base.py 的 SkillAgent 区别：
- SkillAgent: 偏分析型，直接操作数据
- SpecialistAgent: 偏交互型，通过 ToolGateway 调用工具

共同点：
- 都受三条硬约束校验
- 都有决策留痕
- 都支持双层推理
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from ..scene_session import SessionContext, UserRole
from ..tool_gateway import ToolCallResult, ToolGateway

logger = structlog.get_logger()


@dataclass
class SpecialistResult:
    """专业 Agent 执行结果"""
    success: bool
    agent_id: str
    action: str
    # 给用户的回复
    message: str = ""
    # 结构化数据
    data: dict = field(default_factory=dict)
    # 建议的工具调用（需用户确认的）
    pending_tool_calls: list[dict] = field(default_factory=list)
    # 推理过程（留痕）
    reasoning: str = ""
    confidence: float = 0.0
    # 约束校验
    constraints_passed: bool = True
    constraints_detail: dict = field(default_factory=dict)
    execution_ms: int = 0
    error: Optional[str] = None


class SpecialistAgent(ABC):
    """专业 Agent 基类

    每个专业 Agent 负责一个业务场景，通过 ToolGateway 执行操作。
    """
    agent_id: str = "base_specialist"
    agent_name: str = "Base Specialist"
    description: str = ""
    priority: str = "P1"

    def __init__(
        self,
        tool_gateway: ToolGateway,
        model_router: Optional[Any] = None,
    ):
        self.tool_gateway = tool_gateway
        self._router = model_router

    async def handle(
        self,
        action: str,
        params: dict,
        context: SessionContext,
    ) -> SpecialistResult:
        """统一入口 — 执行 + 约束校验 + 决策留痕"""
        start = time.perf_counter()

        try:
            result = await self.execute(action, params, context)
        except Exception as e:  # noqa: BLE001 — 最外层兜底
            logger.error(
                "specialist_error",
                agent=self.agent_id,
                action=action,
                error=str(e),
                exc_info=True,
            )
            result = SpecialistResult(
                success=False,
                agent_id=self.agent_id,
                action=action,
                error=str(e),
                message=f"执行出错: {e}",
            )

        result.execution_ms = int((time.perf_counter() - start) * 1000)
        result.agent_id = self.agent_id

        # 三条硬约束校验
        from ...agents.constraints import ConstraintChecker
        checker = ConstraintChecker()
        constraint_result = checker.check_all(result.data)
        result.constraints_passed = constraint_result.passed
        result.constraints_detail = constraint_result.to_dict()

        logger.info(
            "specialist_executed",
            agent=self.agent_id,
            action=action,
            success=result.success,
            confidence=result.confidence,
            constraints_passed=result.constraints_passed,
            ms=result.execution_ms,
        )

        return result

    @abstractmethod
    async def execute(
        self,
        action: str,
        params: dict,
        context: SessionContext,
    ) -> SpecialistResult:
        """子类实现具体业务逻辑"""
        ...

    @abstractmethod
    def get_supported_actions(self) -> list[str]:
        """返回支持的 action 列表"""
        ...

    async def call_tool(
        self,
        tool_name: str,
        params: dict,
        context: SessionContext,
    ) -> ToolCallResult:
        """通过 ToolGateway 调用工具"""
        return await self.tool_gateway.call_tool(
            tool_name=tool_name,
            params=params,
            caller_role=context.user_role,
            caller_agent=self.agent_id,
            tenant_id=context.tenant_id,
        )

    async def llm_reason(
        self,
        prompt: str,
        context: SessionContext,
        task_type: str = "agent_decision",
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """通过 ModelRouter 进行 LLM 推理"""
        if not self._router:
            return None

        system = (
            f"你是屯象OS的{self.agent_name}。\n"
            f"当前角色: {context.user_role.value}\n"
            f"当前班次: {context.shift_period.value}\n"
            f"门店ID: {context.store_id or '总部'}\n"
            "请基于上下文给出专业的分析和建议。"
        )

        return await self._router.complete(
            tenant_id=context.tenant_id,
            task_type=task_type,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=max_tokens,
        )

    def get_info(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "priority": self.priority,
            "supported_actions": self.get_supported_actions(),
        }
