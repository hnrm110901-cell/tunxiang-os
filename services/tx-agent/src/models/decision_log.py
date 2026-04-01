"""Agent 决策留痕 — 每个决策必须有完整审计记录"""
import uuid

from sqlalchemy import String, Float, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentDecisionLog(TenantBase):
    """Agent 决策日志 — 强制留痕（V3.0 CLAUDE.md 第九章）"""
    __tablename__ = "agent_decision_logs"

    agent_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment="Agent标识")
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="决策类型")
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    # 推理链路
    input_context: Mapped[dict] = mapped_column(JSON, nullable=False, comment="输入上下文")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True, comment="推理过程（orchestrator plan JSON）")
    output_action: Mapped[dict] = mapped_column(JSON, nullable=False, comment="输出动作")

    # 三条硬约束校验结果
    constraints_check: Mapped[dict] = mapped_column(JSON, nullable=False, comment="三条硬约束校验")

    # 元数据
    confidence: Mapped[float] = mapped_column(Float, nullable=False, comment="置信度 0-1")
    execution_ms: Mapped[int | None] = mapped_column(comment="执行耗时ms")
    inference_layer: Mapped[str | None] = mapped_column(String(20), comment="edge/cloud")
    model_id: Mapped[str | None] = mapped_column(String(100), comment="使用的模型ID")

    # 关联 ExecutionPlan
    plan_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True, comment="关联的 ExecutionPlan.plan_id")

    decided_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
