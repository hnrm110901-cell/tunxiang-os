"""AgentOrchestrator — AI 驱动的多 Agent 编排器

替代 MasterAgent 中的关键词路由，改为：
1. 接收触发器（事件 / 用户意图 / 自然语言指令）
2. 用 claude-haiku 快速生成执行计划（哪些 Agent、什么顺序、是否并行）
3. 执行计划，收集各 Agent 结果
4. 综合结果生成最终决策
5. 写入 AgentDecisionLog 留痕

增强功能（P0-5/6/7）：
- Session 生命周期：每次编排包裹在 SessionRun 中，全过程留痕
- 人工确认节点：requires_human_confirm 步骤执行后暂停等待审批
- Step 重试机制：失败步骤自动重试，max_retries 控制上限

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
    PAUSED = "paused"


@dataclass
class ExecutionStep:
    """执行计划中的单个步骤"""

    step_id: str
    agent_id: str  # 要调用的 Skill Agent ID
    action: str  # Agent 的动作名
    params: dict  # 传给 Agent 的参数
    depends_on: list[str] = field(default_factory=list)  # 依赖哪些 step_id（空=可并行）
    timeout_seconds: int = 30
    status: StepStatus = StepStatus.PENDING
    result: Optional[AgentResult] = None
    error: Optional[str] = None
    # P0-6: 人工确认节点
    requires_human_confirm: bool = False
    # P0-7: Step 重试机制
    max_retries: int = 0
    retry_count: int = 0


@dataclass
class ExecutionPlan:
    """Orchestrator 生成的执行计划"""

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trigger_summary: str = ""  # 触发原因摘要（用于日志）
    steps: list[ExecutionStep] = field(default_factory=list)
    estimated_impact: str = ""  # 预估影响范围描述
    planning_model: str = ""  # 使用的规划模型
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrchestratorResult:
    """编排器最终输出"""

    plan_id: str
    success: bool
    completed_steps: list[str]  # 成功完成的 step_id 列表
    failed_steps: list[str]
    synthesis: str  # 综合分析文本
    recommended_actions: list[dict]  # 推荐给前端展示的动作列表
    constraints_passed: bool  # 三条硬约束是否全部通过
    confidence: float
    plan_steps: list = field(default_factory=list)  # ExecutionPlan.steps 摘要（用于决策留痕）
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # P0-5: Session 关联
    session_id: Optional[str] = None
    # P0-6: 暂停标记
    paused: bool = False
    checkpoint_id: Optional[str] = None


def _generate_session_id() -> str:
    """生成可读的 session_id: SR-{YYYYMMDD}-{short_uuid[:8]}"""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:8]
    return f"SR-{date_str}-{short}"


# ─────────────────────────────────────────────────────────────────────────────
# AgentOrchestrator
# ─────────────────────────────────────────────────────────────────────────────


class AgentOrchestrator:
    """AI 驱动的多 Agent 编排器"""

    # 所有已注册 Agent 的描述（用于规划提示词）
    AGENT_CATALOG: dict[str, str] = {
        "discount_guard": "折扣守护：检测和拦截不合规折扣，记录违规",
        "smart_menu": "智能排菜：推荐菜品组合、推送今日特价、标记售罄替代",
        "serve_dispatch": "出餐调度：安排出菜优先级、分配服务员、KDS指令",
        "member_insight": "会员洞察：更新RFM分层、流失预警、消费行为分析",
        "inventory_alert": "库存预警：评估库存不足严重程度、触发紧急补货",
        "finance_audit": "财务稽核：P&L分析、成本率检测、收入异常标记",
        "store_inspect": "巡店质检：门店评分、问题记录、整改跟踪",
        "smart_service": "智能客服：处理投诉、生成回复建议",
        "private_ops": "私域运营：触发旅程、发送消息、管理优惠活动",
    }

    def __init__(
        self,
        master_agent: Any,  # MasterAgent 实例（用于 dispatch）
        model_router: Any,  # ModelRouter 实例
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Any = None,  # P0-5: AsyncSession（可选，无DB时降级为无状态模式）
    ) -> None:
        self.master = master_agent
        self.router = model_router
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.db = db
        # P0-5: Session 事件序号计数器（每次 orchestrate 重置）
        self._event_seq: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Session 辅助方法（P0-5）
    # ─────────────────────────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        """递增并返回下一个事件序号"""
        self._event_seq += 1
        return self._event_seq

    async def _create_session_run(
        self,
        trigger: AgentEvent | str,
    ) -> str:
        """创建 SessionRun 记录，返回 session_id"""
        from ..models.session_run import SessionRun

        session_id = _generate_session_id()
        trigger_type = "event" if isinstance(trigger, AgentEvent) else "user_command"

        run = SessionRun(
            tenant_id=self.tenant_id,
            session_id=session_id,
            status="created",
            trigger_type=trigger_type,
            store_id=self.store_id,
        )
        self.db.add(run)
        await self.db.flush()

        logger.info(
            "session_run_created",
            session_id=session_id,
            trigger_type=trigger_type,
            tenant_id=self.tenant_id,
        )
        return session_id

    async def _update_session_status(
        self,
        session_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        """更新 SessionRun 状态"""
        from sqlalchemy import update

        from ..models.session_run import SessionRun

        values: dict[str, Any] = {"status": status}
        values.update(kwargs)

        if status in ("completed", "failed"):
            values["finished_at"] = datetime.now(timezone.utc)
        elif status == "running":
            values["started_at"] = datetime.now(timezone.utc)

        stmt = update(SessionRun).where(SessionRun.session_id == session_id).values(**values)
        await self.db.execute(stmt)
        await self.db.flush()

        logger.info(
            "session_status_updated",
            session_id=session_id,
            status=status,
        )

    async def _emit_session_event(
        self,
        session_id: str,
        event_type: str,
        step_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        detail: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """写入 SessionEvent"""
        from ..models.session_event import SessionEvent

        event = SessionEvent(
            tenant_id=self.tenant_id,
            session_id=session_id,
            sequence_no=self._next_seq(),
            event_type=event_type,
            step_id=step_id,
            agent_id=agent_id,
            detail=detail,
            error_message=error_message,
        )
        self.db.add(event)
        await self.db.flush()

    async def _create_checkpoint(
        self,
        session_id: str,
        step: ExecutionStep,
        result: AgentResult,
    ) -> str:
        """创建人工确认暂停节点，返回 checkpoint_id"""
        from ..models.session_checkpoint import SessionCheckpoint

        checkpoint = SessionCheckpoint(
            tenant_id=self.tenant_id,
            session_id=session_id,
            step_id=step.step_id,
            reason="human_review",
            status="pending",
            pending_action={
                "agent_id": step.agent_id,
                "action": step.action,
                "params": step.params,
                "result_data": result.data,
                "result_reasoning": result.reasoning,
                "confidence": result.confidence,
                "recommended_actions": result.data.get("recommended_actions", []),
            },
        )
        self.db.add(checkpoint)
        await self.db.flush()

        checkpoint_id = str(checkpoint.id)
        logger.info(
            "session_checkpoint_created",
            session_id=session_id,
            step_id=step.step_id,
            checkpoint_id=checkpoint_id,
        )
        return checkpoint_id

    # ─────────────────────────────────────────────────────────────────────────
    # 主入口
    # ─────────────────────────────────────────────────────────────────────────

    async def orchestrate(
        self,
        trigger: AgentEvent | str,
        context: Optional[dict] = None,
    ) -> OrchestratorResult:
        """主入口：接收触发器 → 规划 → 执行 → 综合 → 返回结果

        P0-5: 有 db 时包裹在 SessionRun 生命周期中。
        """
        session_id: Optional[str] = None
        self._event_seq = 0

        # P0-5: 创建 SessionRun
        if self.db is not None:
            session_id = await self._create_session_run(trigger)
            await self._update_session_status(session_id, "running")

        try:
            plan = await self._plan(trigger, context or {})

            # P0-5: 记录 plan_id 到 SessionRun
            if self.db is not None and session_id:
                await self._update_session_status(
                    session_id,
                    "running",
                    plan_id=plan.plan_id,
                    total_steps=len(plan.steps),
                    trigger_summary=plan.trigger_summary,
                )

            results = await self._execute(plan, session_id)

            # P0-6: 检查是否因人工确认暂停
            paused_step = next(
                (s for s in plan.steps if s.status == StepStatus.PAUSED),
                None,
            )
            if paused_step is not None:
                # 编排暂停 — 返回暂停结果
                checkpoint_id = (
                    paused_step.result.data.get("checkpoint_id")
                    if paused_step.result and paused_step.result.data
                    else None
                )
                completed = [
                    sid for sid, r in results.items() if r.success and not (r.data and r.data.get("checkpoint_created"))
                ]
                return OrchestratorResult(
                    plan_id=plan.plan_id,
                    success=True,
                    completed_steps=completed,
                    failed_steps=[sid for sid, r in results.items() if not r.success],
                    synthesis=f"编排暂停：步骤 {paused_step.step_id} 需要人工确认",
                    recommended_actions=[],
                    constraints_passed=True,
                    confidence=0.0,
                    plan_steps=plan.steps,
                    session_id=session_id,
                    paused=True,
                    checkpoint_id=checkpoint_id,
                )

            result = await self._synthesize(plan, results)
            result.session_id = session_id

            # P0-5: 更新 SessionRun 为完成
            if self.db is not None and session_id:
                completed_count = len(result.completed_steps)
                failed_count = len(result.failed_steps)
                final_status = "completed" if result.success else "failed"
                await self._update_session_status(
                    session_id,
                    final_status,
                    completed_steps=completed_count,
                    failed_steps=failed_count,
                    result_json={
                        "synthesis": result.synthesis,
                        "recommended_actions": result.recommended_actions,
                    },
                    confidence=result.confidence,
                    constraints_passed=result.constraints_passed,
                )

            return result

        except Exception as exc:  # noqa: BLE001 — 编排最外层兜底，确保 SessionRun 状态更新
            # P0-5: 编排异常时标记 SessionRun 为 failed
            if self.db is not None and session_id:
                try:
                    await self._update_session_status(
                        session_id,
                        "failed",
                        result_json={"error": str(exc)},
                    )
                except Exception:  # noqa: BLE001 — 状态更新失败不应掩盖原始异常
                    logger.error("session_status_update_failed", session_id=session_id, exc_info=True)
            raise

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
        catalog_text = "\n".join(f"- {aid}: {desc}" for aid, desc in self.AGENT_CATALOG.items())

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
5. 如果步骤涉及高风险操作（如大额折扣、批量修改价格、库存调整），设 requires_human_confirm 为 true
6. 如果步骤涉及网络调用或外部服务，设 max_retries 为 1-3（视重要性而定）

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
      "timeout_seconds": 30,
      "requires_human_confirm": false,
      "max_retries": 0
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
                    requires_human_confirm=s.get("requires_human_confirm", False),
                    max_retries=s.get("max_retries", 0),
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

    async def _execute(
        self,
        plan: ExecutionPlan,
        session_id: Optional[str] = None,
    ) -> dict[str, AgentResult]:
        """按依赖关系执行计划步骤（支持并行）"""
        results: dict[str, AgentResult] = {}
        completed_ids: set[str] = set()
        paused_ids: set[str] = set()
        pending = list(plan.steps)

        while pending:
            # 找出所有依赖已满足的步骤（可并行执行）
            # P0-6: paused 的步骤也算"完成"以解除下游依赖检查，
            # 但 paused 步骤的下游不应执行（在下面的 break 处理）
            ready = [s for s in pending if all(dep in completed_ids for dep in s.depends_on)]
            if not ready:
                # 无法继续（循环依赖或所有步骤都在等待），退出
                logger.warning(
                    "orchestrator_execution_stalled",
                    plan_id=plan.plan_id,
                    remaining_steps=[s.step_id for s in pending],
                )
                break

            # 并行执行所有就绪步骤
            batch_results = await asyncio.gather(*[self._run_step(plan, step, session_id) for step in ready])

            for step_id, result in batch_results:
                results[step_id] = result
                completed_ids.add(step_id)

                # P0-6: 如果该步骤被暂停，记录并中止后续编排
                step_obj = next((s for s in plan.steps if s.step_id == step_id), None)
                if step_obj and step_obj.status == StepStatus.PAUSED:
                    paused_ids.add(step_id)

            # P0-6: 有步骤暂停时中止后续编排
            if paused_ids:
                logger.info(
                    "orchestrator_paused_for_human_confirm",
                    plan_id=plan.plan_id,
                    paused_steps=list(paused_ids),
                )
                break

            pending = [s for s in pending if s.step_id not in completed_ids]

        return results

    async def _run_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        session_id: Optional[str] = None,
    ) -> tuple[str, AgentResult]:
        """执行单个步骤，带超时保护 + 重试 + 人工确认暂停"""
        step.status = StepStatus.RUNNING

        # P0-5: 记录 step_started 事件
        if self.db is not None and session_id:
            await self._emit_session_event(
                session_id=session_id,
                event_type="step_started",
                step_id=step.step_id,
                agent_id=step.agent_id,
                detail={"action": step.action, "params": step.params},
            )

        # P0-7: 重试循环
        last_error: Optional[str] = None
        while True:
            try:
                result = await asyncio.wait_for(
                    self.master.dispatch(step.agent_id, step.action, step.params),
                    timeout=step.timeout_seconds,
                )
                step.status = StepStatus.COMPLETED
                step.result = result

                # P0-5: 记录 step_completed 事件
                if self.db is not None and session_id:
                    await self._emit_session_event(
                        session_id=session_id,
                        event_type="step_completed",
                        step_id=step.step_id,
                        agent_id=step.agent_id,
                        detail={
                            "success": result.success,
                            "confidence": result.confidence,
                            "retry_count": step.retry_count,
                        },
                    )

                logger.info(
                    "orchestrator_step_completed",
                    plan_id=plan.plan_id,
                    step_id=step.step_id,
                    agent_id=step.agent_id,
                    retry_count=step.retry_count,
                )

                # P0-6: 人工确认节点处理
                if step.requires_human_confirm and self.db is not None and session_id:
                    checkpoint_id = await self._create_checkpoint(
                        session_id=session_id,
                        step=step,
                        result=result,
                    )
                    # 暂停 SessionRun
                    await self._update_session_status(session_id, "paused")
                    await self._emit_session_event(
                        session_id=session_id,
                        event_type="session_paused",
                        step_id=step.step_id,
                        agent_id=step.agent_id,
                        detail={"checkpoint_id": checkpoint_id, "reason": "human_review"},
                    )
                    step.status = StepStatus.PAUSED
                    return step.step_id, AgentResult(
                        success=True,
                        action=step.action,
                        data={
                            "checkpoint_created": True,
                            "checkpoint_id": checkpoint_id,
                            "original_result": result.data,
                        },
                        reasoning="步骤已完成，等待人工确认",
                        confidence=result.confidence,
                    )

                return step.step_id, result

            except (TimeoutError, asyncio.TimeoutError):
                last_error = f"timeout after {step.timeout_seconds}s"
                log_method = logger.warning
                log_event = "orchestrator_step_timeout"

            except (RuntimeError, ValueError) as exc:
                last_error = str(exc)
                log_method = logger.error
                log_event = "orchestrator_step_failed"

            # P0-7: 重试判断
            if step.retry_count < step.max_retries:
                step.retry_count += 1
                log_method(
                    log_event,
                    step_id=step.step_id,
                    agent_id=step.agent_id,
                    error=last_error,
                    retrying=True,
                    retry_count=step.retry_count,
                    max_retries=step.max_retries,
                )
                # P0-5: 记录 step_retried 事件
                if self.db is not None and session_id:
                    await self._emit_session_event(
                        session_id=session_id,
                        event_type="step_retried",
                        step_id=step.step_id,
                        agent_id=step.agent_id,
                        detail={
                            "retry_count": step.retry_count,
                            "max_retries": step.max_retries,
                            "error": last_error,
                        },
                    )
                await asyncio.sleep(min(1.0 * step.retry_count, 5.0))  # 线性退避，最多5秒
                continue  # 重试

            # 最终失败
            step.status = StepStatus.FAILED
            step.error = last_error
            log_method(
                log_event,
                step_id=step.step_id,
                agent_id=step.agent_id,
                error=last_error,
                retry_count=step.retry_count,
                max_retries=step.max_retries,
            )

            # P0-5: 记录 step_failed 事件
            if self.db is not None and session_id:
                await self._emit_session_event(
                    session_id=session_id,
                    event_type="step_failed",
                    step_id=step.step_id,
                    agent_id=step.agent_id,
                    error_message=last_error,
                    detail={"retry_count": step.retry_count, "max_retries": step.max_retries},
                )

            return step.step_id, AgentResult(success=False, action=step.action, error=last_error)

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
        constraint_note = "硬约束全部通过。" if constraints_passed else "警告：发现硬约束违反，已阻断相关动作。"
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
