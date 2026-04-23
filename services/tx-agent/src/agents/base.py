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
from typing import Any, ClassVar, Optional

import structlog
from sqlalchemy.exc import SQLAlchemyError

from .context import ConstraintContext

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
    agent_level: int = 1  # 1=suggest, 2=auto+rollback, 3=fully_autonomous
    rollback_window_min: int = 30  # Level 2: minutes before auto-commit
    rollback_id: str = ""  # For Level 2 rollback tracking
    # Sprint D1 / PR G：结构化约束输入。优先级：result.context > result.data 组装 > 类级 scope
    context: Optional[ConstraintContext] = None

    # Sprint D2：ROI 三字段 + 证据（v264 迁移）
    # Skill.execute() 填入这些字段，base.run() 写入 agent_decision_logs，mv_agent_roi_monthly 聚合
    saved_labor_hours: float = 0.0             # 节省的人力工时
    prevented_loss_fen: int = 0                # 拦截的损失金额（分）
    improved_kpi: dict = field(default_factory=dict)    # {"revenue_uplift_fen":..., "nps_delta":...}
    roi_evidence: dict = field(default_factory=dict)    # 证据链：{"data_source":..., "sql":..., "event_id":...}


@dataclass
class ActionConfig:
    """Per-action session policy declaration"""
    requires_human_confirm: bool = False
    max_retries: int = 0
    risk_level: str = "low"  # low/medium/high/critical


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
    agent_level: int = 1  # 1=suggest, 2=auto+rollback, 3=fully_autonomous

    # Sprint D1 / PR G：三条硬约束作用域声明
    #   默认校验全部三条（与旧行为等价）。
    #   只读 / 纯 ETL / 内容生成 Skill 可设为 set()，配合 constraint_waived_reason 解释
    #   迁移期兼容：result.context 优先；否则从 result.data 自动组装；最后用本类级 scope
    constraint_scope: ClassVar[set[str]] = {"margin", "safety", "experience"}
    constraint_waived_reason: ClassVar[Optional[str]] = None

    def __init__(
        self,
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Optional[Any] = None,
        model_router: Optional[Any] = None,
    ):
        self.tenant_id = tenant_id
        self.store_id = store_id
        self._db = db            # AsyncSession，可选
        self._router = model_router  # ModelRouter，可选

    async def run(self, action: str, params: dict[str, Any]) -> AgentResult:
        """统一入口 — 执行 + 约束校验 + 决策留痕 + 自治等级标注

        子类不要覆盖此方法，实现 execute() 即可。
        三级自治机制：
          Level 1: 仅建议，人工决定是否执行
          Level 2: 自动执行 + 30分钟回滚窗口
          Level 3: 完全自主执行
        """
        start = time.perf_counter()

        try:
            result = await self.execute(action, params)
        except Exception as e:  # noqa: BLE001 — Agent最外层兜底，子类可能抛任意异常
            logger.error("agent_error", agent=self.agent_id, action=action, error=str(e), exc_info=True)
            result = AgentResult(
                success=False,
                action=action,
                error=str(e),
                reasoning=f"执行出错: {e}",
            )

        result.execution_ms = int((time.perf_counter() - start) * 1000)

        # 标注自治等级
        result.agent_level = self.agent_level
        if self.agent_level == 2:
            result.rollback_id = str(uuid.uuid4())
            result.rollback_window_min = 30

        # 三条硬约束校验（Sprint D1 / PR G：引入 scope 声明 + 显式豁免 + N/A 标记）
        from .constraints import ConstraintChecker
        checker = ConstraintChecker()

        # 显式豁免：Skill 类级 constraint_scope=set() 表示不适用任何约束
        if not self.constraint_scope:
            if not self.constraint_waived_reason:
                logger.error(
                    "constraint_waiver_missing_reason",
                    agent=self.agent_id,
                    action=action,
                    hint="声明 constraint_scope=set() 时必须同时填 constraint_waived_reason (≥30字符)",
                )
            result.constraints_passed = True
            result.constraints_detail = {
                "passed": True,
                "scope": "waived",
                "waived_reason": self.constraint_waived_reason,
                "scopes_checked": [],
                "scopes_skipped": [],
                "violations": [],
            }
        else:
            # 优先级：result.context > result.data 组装 > 类级 scope
            ctx = result.context or ConstraintContext.from_data(result.data)
            constraint_result = checker.check_all(ctx, scope=self.constraint_scope)

            # 决定 scope 标签（n/a / 单 scope / mixed）
            if not constraint_result.scopes_checked and constraint_result.scopes_skipped:
                # 该校验的都没数据 —— 标 "n/a"，CI 后续可按此统计
                constraint_result.scope = "n/a"
                logger.warning(
                    "constraint_scope_na",
                    agent=self.agent_id,
                    action=action,
                    declared_scope=sorted(self.constraint_scope),
                    skipped=constraint_result.scopes_skipped,
                    hint="Skill 声明需要校验，但 context/data 中没有必要字段",
                )
            elif len(constraint_result.scopes_checked) == 1:
                constraint_result.scope = constraint_result.scopes_checked[0]
            else:
                constraint_result.scope = "mixed"

            result.constraints_passed = constraint_result.passed
            result.constraints_detail = constraint_result.to_dict()

            if not constraint_result.passed:
                logger.warning(
                    "constraint_violation",
                    agent=self.agent_id,
                    action=action,
                    violations=constraint_result.violations,
                )

        # ── Session 事件记录（当 DB 可用时）──
        if self._db is not None:
            try:
                from ..models.session_event import SessionEvent
                session_id = params.get("_session_id")
                if session_id:
                    event = SessionEvent(
                        tenant_id=self.tenant_id,
                        session_id=session_id,
                        sequence_no=params.get("_sequence_no", 0),
                        event_type="step_completed" if result.success else "step_failed",
                        agent_id=self.agent_id,
                        action=action,
                        input_json=params,
                        output_json=result.data,
                        reasoning=result.reasoning,
                        tokens_used=0,
                        duration_ms=result.execution_ms,
                        inference_layer=result.inference_layer,
                    )
                    self._db.add(event)
                    await self._db.flush()
            except (ImportError, AttributeError, TypeError, SQLAlchemyError) as e:
                logger.debug("session_event_skip", reason=str(e))

        logger.info(
            "agent_executed",
            agent=self.agent_id,
            action=action,
            success=result.success,
            confidence=result.confidence,
            constraints_passed=result.constraints_passed,
            agent_level=self.agent_level,
            rollback_id=result.rollback_id,
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

    def get_action_config(self, action: str) -> ActionConfig:
        """Override in subclass to declare per-action session policies.

        Used by Orchestrator to decide:
        - requires_human_confirm → create checkpoint, pause session
        - max_retries → auto-retry on failure
        - risk_level → observability tagging
        """
        return ActionConfig()

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
