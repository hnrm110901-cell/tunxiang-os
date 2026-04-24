"""DecisionLogService — Agent 决策留痕服务

将 Orchestrator 和 Skill Agent 的决策持久化到 agent_decision_logs 表。
留痕失败只 warn，绝不阻断主业务流程。
"""

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.decision_log import AgentDecisionLog

logger = structlog.get_logger()


# Sprint D2（v264）：ROI writeback flag 名称。
# 独立常量避免在主业务链路里 import shared.feature_flags，保持留痕子系统轻量。
# 真实评估时通过 shared.feature_flags.is_enabled 读取。
_ROI_WRITEBACK_FLAG = "agent.roi.writeback"


def _roi_writeback_enabled() -> bool:
    """评估 ROI writeback flag。

    懒加载 feature_flags 客户端 — 在测试环境/早期启动阶段 feature_flags
    可能未就绪；此处 import 失败即视为 flag off，确保留痕链路永远能降级。
    """
    try:
        from shared.feature_flags import is_enabled  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        return bool(is_enabled(_ROI_WRITEBACK_FLAG))
    except (AttributeError, KeyError, ValueError) as exc:
        logger.debug("roi_writeback_flag_eval_failed", error=str(exc))
        return False


def _apply_roi_fields(
    record: AgentDecisionLog,
    roi: Optional[dict[str, Any]],
) -> None:
    """按 flag 守护写入 ROI 四字段。

    Args:
        record: 即将 add 到 session 的 AgentDecisionLog 实例。
        roi:    上游计算出的 ROI dict，形如：
                {
                    "saved_labor_hours": 0.5,          # float / Decimal / None
                    "prevented_loss_fen": 12000,       # int / None
                    "improved_kpi": {"metric": "gross_margin", "delta_pct": 1.8},
                    "roi_evidence": {"source": "discount_guard_v2", ...},
                }

    Rule:
        - flag off  → 全部字段保持 None（向前兼容）
        - flag on + roi=None → 全部字段保持 None（无计算数据）
        - flag on + roi dict → 按字段校验后写入（未提供的字段保持 None）
    """
    if not roi or not _roi_writeback_enabled():
        return

    saved = roi.get("saved_labor_hours")
    if isinstance(saved, (int, float, Decimal)):
        record.saved_labor_hours = Decimal(str(saved))

    prevented = roi.get("prevented_loss_fen")
    if isinstance(prevented, int) and not isinstance(prevented, bool):
        record.prevented_loss_fen = prevented

    kpi = roi.get("improved_kpi")
    if isinstance(kpi, dict):
        record.improved_kpi = kpi

    evidence = roi.get("roi_evidence")
    if isinstance(evidence, dict):
        record.roi_evidence = evidence


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
        roi: Optional[dict[str, Any]] = None,
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
            roi: Sprint D2 ROI 四字段 dict（可选）。仅当 flag
                 `agent.roi.writeback` 开启时写入；关闭时四字段保持 NULL。
                 形如：{saved_labor_hours, prevented_loss_fen,
                        improved_kpi, roi_evidence}。
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
            # Sprint D2: flag on 时才注入 ROI；flag off 时四字段保持 NULL
            _apply_roi_fields(record, roi)
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
        roi: Optional[dict[str, Any]] = None,
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
            roi: Sprint D2 ROI 四字段 dict（可选）。仅当 flag
                 `agent.roi.writeback` 开启时写入；若未提供或 flag off，
                 四字段保持 NULL，行为与 v264 前完全一致。
        """
        try:
            result_data: dict = getattr(result, "data", None) or {}
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
                constraints_check=result_data.get("constraints_check", {}) if isinstance(result_data, dict) else {},
                confidence=result_data.get("confidence", 1.0) if isinstance(result_data, dict) else 1.0,
                plan_id=plan_id,
            )
            # Sprint D2: ROI writeback（flag off 时零影响）
            # 若调用方未显式传 roi，则尝试从 result.data["roi"] 拾取
            effective_roi = roi
            if effective_roi is None and isinstance(result_data, dict):
                candidate = result_data.get("roi")
                if isinstance(candidate, dict):
                    effective_roi = candidate
            _apply_roi_fields(record, effective_roi)
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
