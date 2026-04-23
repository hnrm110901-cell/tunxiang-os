"""DecisionLogService — Agent 决策留痕服务

将 Orchestrator 和 Skill Agent 的决策持久化到 agent_decision_logs 表。
留痕失败只 warn，绝不阻断主业务流程。
"""
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.decision_log import AgentDecisionLog

logger = structlog.get_logger()


class DecisionLogService:
    """Agent 决策留痕服务（所有方法为 static，无状态）"""

    @staticmethod
    async def log_orchestrator_result(
        db: AsyncSession,
        tenant_id: str,
        store_id: Optional[str],
        plan_id: str,
        trigger_summary: str,
        plan_steps: list,
        orchestrator_result: object,
    ) -> None:
        """记录 Orchestrator 的多 Agent 编排决策。

        Args:
            db: 已绑定租户 RLS 的 AsyncSession。
            tenant_id: 租户 UUID 字符串。
            store_id: 门店 UUID 字符串，可为 None。
            plan_id: ExecutionPlan.plan_id。
            trigger_summary: 触发原因一句话摘要。
            plan_steps: ExecutionPlan.steps 列表（ExecutionStep 实例）。
            orchestrator_result: OrchestratorResult 实例。
        """
        try:
            steps_snapshot = [
                {
                    "step_id": s.step_id,
                    "agent_id": s.agent_id,
                    "action": s.action,
                }
                for s in plan_steps
            ]
            record = AgentDecisionLog(
                tenant_id=UUID(tenant_id),
                store_id=UUID(store_id) if store_id else None,
                agent_id="orchestrator",
                decision_type="multi_agent_workflow",
                input_context={"trigger": trigger_summary},
                reasoning=str(steps_snapshot),
                output_action={
                    "completed_steps": orchestrator_result.completed_steps,  # type: ignore[attr-defined]
                    "failed_steps": orchestrator_result.failed_steps,  # type: ignore[attr-defined]
                    "recommended_actions": orchestrator_result.recommended_actions,  # type: ignore[attr-defined]
                    "synthesis": orchestrator_result.synthesis,  # type: ignore[attr-defined]
                },
                constraints_check={
                    "passed": orchestrator_result.constraints_passed,  # type: ignore[attr-defined]
                },
                confidence=orchestrator_result.confidence,  # type: ignore[attr-defined]
                plan_id=plan_id,
            )
            db.add(record)
            await db.flush()
            logger.info(
                "decision_log_written",
                plan_id=plan_id,
                agent_id="orchestrator",
                confidence=orchestrator_result.confidence,  # type: ignore[attr-defined]
            )
        except (ValueError, TypeError, AttributeError) as exc:
            # 留痕失败不阻断主业务
            logger.warning(
                "decision_log_failed",
                plan_id=plan_id,
                agent_id="orchestrator",
                error=str(exc),
            )

    @staticmethod
    async def log_skill_result(
        db: AsyncSession,
        tenant_id: str,
        agent_id: str,
        action: str,
        input_context: dict,
        result: object,
        plan_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> None:
        """记录单个 Skill Agent 的执行决策。

        Args:
            db: 已绑定租户 RLS 的 AsyncSession。
            tenant_id: 租户 UUID 字符串。
            agent_id: Skill Agent 标识，如 "discount_guard"。
            action: 执行的动作名，如 "detect_anomaly"。
            input_context: 传入 Agent 的上下文参数。
            result: AgentResult 实例。
            plan_id: 关联 ExecutionPlan.plan_id，可为 None。
            store_id: 门店 UUID 字符串，可为 None。
        """
        try:
            result_data: dict = getattr(result, "data", None) or {}

            # Sprint D2：从 AgentResult 提取 ROI 三字段（未填则默认 0/{}）
            saved_labor_hours = float(getattr(result, "saved_labor_hours", 0.0) or 0.0)
            prevented_loss_fen = int(getattr(result, "prevented_loss_fen", 0) or 0)
            improved_kpi = getattr(result, "improved_kpi", None) or {}
            roi_evidence = getattr(result, "roi_evidence", None) or {}
            if not isinstance(improved_kpi, dict):
                improved_kpi = {}
            if not isinstance(roi_evidence, dict):
                roi_evidence = {}

            record = AgentDecisionLog(
                tenant_id=UUID(tenant_id),
                store_id=UUID(store_id) if store_id else None,
                agent_id=agent_id,
                decision_type="skill_execution",
                input_context=input_context,
                output_action={
                    "action": action,
                    "success": getattr(result, "success", False),
                    "data": result_data,
                },
                constraints_check=result_data.get("constraints_check", {})
                if isinstance(result_data, dict)
                else {},
                confidence=result_data.get("confidence", 1.0)
                if isinstance(result_data, dict)
                else 1.0,
                plan_id=plan_id,
                # Sprint D2：ROI 写入（v264 迁移新增列）
                saved_labor_hours=saved_labor_hours,
                prevented_loss_fen=prevented_loss_fen,
                improved_kpi=improved_kpi,
                roi_evidence=roi_evidence,
            )
            db.add(record)
            await db.flush()
            logger.info(
                "skill_decision_log_written",
                plan_id=plan_id,
                agent_id=agent_id,
                action=action,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "skill_decision_log_failed",
                plan_id=plan_id,
                agent_id=agent_id,
                error=str(exc),
            )
