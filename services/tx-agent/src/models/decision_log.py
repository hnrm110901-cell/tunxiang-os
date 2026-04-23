"""Agent 决策留痕 — 每个决策必须有完整审计记录"""
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, Float, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import BIGINT, JSON, JSONB, UUID
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

    # Sprint D2：ROI 三字段 + 证据（v264 迁移）
    # 注：v264 用 DEFAULT 0 / '{}'::jsonb，ORM 端也给对应默认，避免旧代码路径 None
    saved_labor_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=True, default=Decimal("0"),
        comment="节省的人力工时（分析/盘点/跑腿代替）",
    )
    prevented_loss_fen: Mapped[int] = mapped_column(
        BIGINT, nullable=True, default=0,
        comment="拦截的损失金额（违规折扣/食安违规/浪费/重复支付，单位分）",
    )
    improved_kpi: Mapped[dict] = mapped_column(
        JSONB, nullable=True, default=dict,
        comment='正向 KPI 变化，例：{"revenue_uplift_fen": 500, "nps_delta": 0.3}',
    )
    roi_evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=True, default=dict,
        comment="证据链：数据源 URL / SQL / 事件 ID / 验证方式",
    )

    decided_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
