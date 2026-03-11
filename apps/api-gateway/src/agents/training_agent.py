"""
TrainingAgent - 员工培训管理智能体

负责：培训需求评估、培训计划生成、进度追踪、技能差距分析。
当前阶段：路由已注册，核心业务逻辑待实现。
"""
import time
from typing import Any, Dict, List

import structlog

from src.core.base_agent import AgentResponse, BaseAgent

logger = structlog.get_logger()

_SUPPORTED_ACTIONS = [
    "assess_training_needs",
    "generate_training_plan",
    "get_training_progress",
    "analyze_skill_gaps",
    "list_training_records",
    "get_certification_status",
]


class TrainingAgent(BaseAgent):
    """员工培训管理智能体"""

    def __init__(self):
        super().__init__(config={})

    def get_supported_actions(self) -> List[str]:
        return _SUPPORTED_ACTIONS

    async def execute(self, action: str, params: Dict[str, Any]) -> AgentResponse:
        start = time.time()
        store_id = params.get("store_id", "")
        logger.info("training_agent.execute", action=action, store_id=store_id)

        if action not in _SUPPORTED_ACTIONS:
            return AgentResponse(
                success=False,
                error=f"不支持的操作: {action}。支持: {', '.join(_SUPPORTED_ACTIONS)}",
                execution_time=time.time() - start,
            )

        logger.warning(
            "training_agent.not_implemented",
            action=action,
            store_id=store_id,
            note="TrainingAgent 业务逻辑待实现，当前返回空结构",
        )
        return AgentResponse(
            success=True,
            data={
                "action": action,
                "store_id": store_id,
                "status": "not_implemented",
                "message": f"TrainingAgent.{action} 尚未实现，培训数据请通过 PerformanceAgent 获取",
            },
            execution_time=time.time() - start,
        )
