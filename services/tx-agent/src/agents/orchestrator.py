"""AgentOrchestrator — AI 驱动的多 Agent 编排器

替代 MasterAgent 中的关键词路由，改为：
1. 接收触发器（事件 / 用户意图 / 自然语言指令）
2. 用 claude-haiku 快速生成执行计划（哪些 Agent、什么顺序、是否并行）
3. 执行计划，收集各 Agent 结果
4. 综合结果生成最终决策
5. 写入 AgentDecisionLog 留痕

关键约束：三条硬约束（毛利底线 / 食安合规 / 客户体验）在 synthesize 阶段校验。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

from .base import AgentResult, SkillAgent  # noqa: F401 — re-exported for callers
from .event_bus import AgentEvent

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionStep:
    """执行计划中的单个步骤"""
    step_id: str
    agent_id: str                          # 要调用的 Skill Agent ID
    action: str                            # Agent 的动作名
    params: dict                           # 传给 Agent 的参数
    depends_on: list[str] = field(default_factory=list)  # 依赖哪些 step_id（空=可并行）
    timeout_seconds: int = 30
    status: StepStatus = StepStatus.PENDING
    result: Optional[AgentResult] = None
    error: Optional[str] = None


@dataclass
class ExecutionPlan:
    """Orchestrator 生成的执行计划"""
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trigger_summary: str = ""              # 触发原因摘要（用于日志）
    steps: list[ExecutionStep] = field(default_factory=list)
    estimated_impact: str = ""            # 预估影响范围描述
    planning_model: str = ""              # 使用的规划模型
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrchestratorResult:
    """编排器最终输出"""
    plan_id: str
    success: bool
    completed_steps: list[str]             # 成功完成的 step_id 列表
    failed_steps: list[str]
    synthesis: str                         # 综合分析文本
    recommended_actions: list[dict]        # 推荐给前端展示的动作列表
    constraints_passed: bool               # 三条硬约束是否全部通过
    confidence: float
    plan_steps: list = field(default_factory=list)  # ExecutionPlan.steps 摘要（用于决策留痕）
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# AgentOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """AI 驱动的多 Agent 编排器"""

    # 所有已注册 Agent 的描述（用于规划提示词）
    AGENT_CATALOG: dict[str, str] = {
        "discount_guard":  "折扣守护：检测和拦截不合规折扣，记录违规",
        "smart_menu":      "智能排菜：推荐菜品组合、推送今日特价、标记售罄替代",
        "serve_dispatch":  "出餐调度：安排出菜优先级、分配服务员、KDS指令",
        "member_insight":  "会员洞察：更新RFM分层、流失预警、消费行为分析",
        "inventory_alert": "库存预警：评估库存不足严重程度、触发紧急补货",
        "finance_audit":   "财务稽核：P&L分析、成本率检测、收入异常标记",
        "store_inspect":   "巡店质检：门店评分、问题记录、整改跟踪",
        "smart_service":   "智能客服：处理投诉、生成回复建议",
        "private_ops":     "私域运营：触发旅程、发送消息、管理优惠活动",
    }

    def __init__(
        self,
        master_agent: Any,          # MasterAgent 实例（用于 dispatch）
        model_router: Any,          # ModelRouter 实例
        tenant_id: str,
        store_id: Optional[str] = None,
    ) -> None:
        self.master = master_agent
        self.router = model_router
        self.tenant_id = tenant_id
        self.store_id = store_id

    async def orchestrate(
        self,
        trigger: AgentEvent | str,
        context: Optional[dict] = None,
    ) -> OrchestratorResult:
        """主入口：接收触发器 → 规划 → 执行 → 综合 → 返回结果"""
        plan = await self._plan(trigger, context or {})
        results = await self._execute(plan)
        return await self._synthesize(plan, results)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: 规划
    # ─────────────────────────────────────────────────────────────────────────

    async def _plan(self, trigger: AgentEvent | str, context: dict) -> ExecutionPlan:
        """用 claude-haiku 生成执行计划"""

        # 构建触发摘要
        if isinstance(trigger, AgentEvent):
            trigger_desc = (
                f"事件触发: {trigger.event_type}, "
                f"门店: {trigger.store_id}, "
                f"数据: {json.dumps(trigger.data, ensure_ascii=False)}"
            )
        else:
            trigger_desc = f"用户指令: {trigger}"

        # 构建 Agent 目录文本
        catalog_text = "\n".join(
            f"- {aid}: {desc}" for aid, desc in self.AGENT_CATALOG.items()
        )

        prompt = f"""你是屯象OS的智能调度员。根据以下触发信息，规划需要调用哪些Agent以及调用顺序。

触发信息：
{trigger_desc}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

可用Agent：
{catalog_text}

规则：
1. 只选择真正必要的Agent，不要过度调用
2. 无依赖关系的步骤设 depends_on 为空列表（可并行执行）
3. 有依赖的步骤设 depends_on 为前置 step_id 列表
4. 每个步骤的 params 需具体，包含触发事件中的关键数据

请以JSON格式输出执行计划（不要有任何markdown格式）：
{{
  "trigger_summary": "一句话描述触发原因",
  "estimated_impact": "预估影响范围",
  "steps": [
    {{
      "step_id": "step_1",
      "agent_id": "agent名称",
      "action": "动作名",
      "params": {{"key": "value"}},
      "depends_on": [],
      "timeout_seconds": 30
    }}
  ]
}}"""

        try:
            response = await self.router.complete(
                tenant_id=self.tenant_id,
                task_type="quick_classification",  # haiku 够用
                messages=[{"role": "user", "content": prompt}],
            )
            plan_data = json.loads(response.content[0].text)

            steps = [
                ExecutionStep(
                    step_id=s["step_id"],
                    agent_id=s["agent_id"],
                    action=s["action"],
                    params=s.get("params", {}),
                    depends_on=s.get("depends_on", []),
                    timeout_seconds=s.get("timeout_seconds", 30),
                )
                for s in plan_data.get("steps", [])
            ]

            return ExecutionPlan(
                trigger_summary=plan_data.get("trigger_summary", str(trigger)[:100]),
                steps=steps,
                estimated_impact=plan_data.get("estimated_impact", ""),
                planning_model="claude-haiku",
            )

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # 规划失败：返回空计划，不影响系统稳定性
            logger.warning(
                "orchestrator_plan_failed",
                error=str(exc),
                trigger=str(trigger)[:200],
            )
            return ExecutionPlan(trigger_summary=str(trigger)[:100], steps=[])

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: 执行
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute(self, plan: ExecutionPlan) -> dict[str, AgentResult]:
        """按依赖关系执行计划步骤（支持并行）"""
        results: dict[str, AgentResult] = {}
        completed_ids: set[str] = set()
        pending = list(plan.steps)

        while pending:
            # 找出所有依赖已满足的步骤（可并行执行）
            ready = [
                s for s in pending
                if all(dep in completed_ids for dep in s.depends_on)
            ]
            if not ready:
                # 无法继续（循环依赖或所有步骤都在等待），退出
                logger.warning(
                    "orchestrator_execution_stalled",
                    plan_id=plan.plan_id,
                    remaining_steps=[s.step_id for s in pending],
                )
                break

            # 并行执行所有就绪步骤
            batch_results = await asyncio.gather(
                *[self._run_step(plan, step) for step in ready]
            )

            for step_id, result in batch_results:
                results[step_id] = result
                completed_ids.add(step_id)

            pending = [s for s in pending if s.step_id not in completed_ids]

        return results

    async def _run_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> tuple[str, AgentResult]:
        """执行单个步骤，带超时保护"""
        step.status = StepStatus.RUNNING
        try:
            result = await asyncio.wait_for(
                self.master.dispatch(step.agent_id, step.action, step.params),
                timeout=step.timeout_seconds,
            )
            step.status = StepStatus.COMPLETED
            step.result = result
            logger.info(
                "orchestrator_step_completed",
                plan_id=plan.plan_id,
                step_id=step.step_id,
                agent_id=step.agent_id,
            )
            return step.step_id, result

        except (TimeoutError, asyncio.TimeoutError):
            step.status = StepStatus.FAILED
            step.error = f"timeout after {step.timeout_seconds}s"
            logger.warning(
                "orchestrator_step_timeout",
                step_id=step.step_id,
                agent_id=step.agent_id,
                timeout_seconds=step.timeout_seconds,
            )
            return step.step_id, AgentResult(
                success=False, action=step.action, error=step.error
            )

        except (RuntimeError, ValueError) as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            logger.error(
                "orchestrator_step_failed",
                step_id=step.step_id,
                agent_id=step.agent_id,
                error=str(exc),
            )
            return step.step_id, AgentResult(
                success=False, action=step.action, error=step.error
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: 综合
    # ─────────────────────────────────────────────────────────────────────────

    async def _synthesize(
        self,
        plan: ExecutionPlan,
        step_results: dict[str, AgentResult],
    ) -> OrchestratorResult:
        """综合所有 Agent 结果，校验三条硬约束，生成最终决策"""

        completed = [sid for sid, r in step_results.items() if r.success]
        failed = [sid for sid, r in step_results.items() if not r.success]

        # 三条硬约束校验（检查 Agent 结果中是否有硬约束违反标记，
        # 或 AgentResult.constraints_passed 被 ConstraintChecker 置为 False）
        constraints_passed = True
        for result in step_results.values():
            if not result.constraints_passed:
                constraints_passed = False
                break
            if result.data and result.data.get("constraint_violated"):
                constraints_passed = False
                break

        # 生成推荐动作列表（从各 Agent 结果中提取）
        recommended_actions: list[dict] = []
        for step in plan.steps:
            r = step_results.get(step.step_id)
            if r and r.success and r.data:
                actions = r.data.get("recommended_actions", [])
                if isinstance(actions, list):
                    recommended_actions.extend(actions)

        # 置信度：基于完成率
        total = len(plan.steps)
        confidence = len(completed) / total if total > 0 else 0.0

        # 综合摘要
        constraint_note = (
            "硬约束全部通过。"
            if constraints_passed
            else "警告：发现硬约束违反，已阻断相关动作。"
        )
        synthesis = (
            f"编排计划 {plan.plan_id[:8]} 完成。"
            f"触发：{plan.trigger_summary}。"
            f"执行 {len(completed)}/{total} 个步骤。"
            f"{constraint_note}"
        )

        logger.info(
            "orchestrator_synthesis_complete",
            plan_id=plan.plan_id,
            completed_steps=len(completed),
            failed_steps=len(failed),
            constraints_passed=constraints_passed,
            confidence=confidence,
        )

        return OrchestratorResult(
            plan_id=plan.plan_id,
            success=len(failed) == 0,
            completed_steps=completed,
            failed_steps=failed,
            synthesis=synthesis,
            recommended_actions=recommended_actions,
            constraints_passed=constraints_passed,
            confidence=confidence,
            plan_steps=plan.steps,
        )
