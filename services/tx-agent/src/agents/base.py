"""Skill Agent 基类 — 所有 9 个领域 Agent 继承此类

核心约定：
1. 每个 execute() 必须返回 AgentResult
2. 每个决策必须通过三条硬约束校验
3. 每个决策必须留痕（AgentDecisionLog）
4. 支持双层推理：边缘(Core ML) + 云端(Claude API)
"""
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    action: str
    data: dict = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 0.0
    constraints_passed: bool = True
    constraints_detail: dict = field(default_factory=dict)
    error: Optional[str] = None
    execution_ms: int = 0
    inference_layer: str = "cloud"  # "edge" or "cloud"


class SkillAgent(ABC):
    """Skill Agent 基类

    每个领域 Agent 继承此类并实现 execute()。
    Master Agent 通过 agent_id 路由到对应 Skill Agent。
    """

    agent_id: str = "base"
    agent_name: str = "Base Agent"
    description: str = ""
    priority: str = "P2"  # P0/P1/P2
    run_location: str = "cloud"  # "edge", "cloud", "edge+cloud"

    def __init__(self, tenant_id: str, store_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.store_id = store_id

    async def run(self, action: str, params: dict[str, Any]) -> AgentResult:
        """统一入口 — 执行 + 约束校验 + 决策留痕

        子类不要覆盖此方法，实现 execute() 即可。
        """
        start = time.perf_counter()

        try:
            result = await self.execute(action, params)
        except Exception as e:
            logger.error("agent_error", agent=self.agent_id, action=action, error=str(e))
            result = AgentResult(
                success=False,
                action=action,
                error=str(e),
                reasoning=f"执行出错: {e}",
            )

        result.execution_ms = int((time.perf_counter() - start) * 1000)

        # 三条硬约束校验
        from .constraints import ConstraintChecker
        checker = ConstraintChecker()
        constraint_result = checker.check_all(result.data)
        result.constraints_passed = constraint_result.passed
        result.constraints_detail = constraint_result.to_dict()

        if not constraint_result.passed:
            logger.warning(
                "constraint_violation",
                agent=self.agent_id,
                action=action,
                violations=constraint_result.violations,
            )

        logger.info(
            "agent_executed",
            agent=self.agent_id,
            action=action,
            success=result.success,
            confidence=result.confidence,
            constraints_passed=result.constraints_passed,
            ms=result.execution_ms,
        )

        return result

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        """子类实现具体业务逻辑

        Args:
            action: 动作名（如 "detect_anomaly", "predict_traffic"）
            params: 动作参数

        Returns:
            AgentResult
        """
        ...

    @abstractmethod
    def get_supported_actions(self) -> list[str]:
        """返回该 Agent 支持的所有 action 列表"""
        ...

    def get_info(self) -> dict:
        """返回 Agent 元信息"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "priority": self.priority,
            "run_location": self.run_location,
            "supported_actions": self.get_supported_actions(),
        }
