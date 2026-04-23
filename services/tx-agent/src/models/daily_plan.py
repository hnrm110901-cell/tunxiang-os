"""DailyPlan 模型 — 每日经营计划，Agent 自动生成，店长审批执行"""

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DailyPlan(TenantBase):
    """每日经营计划 — DailyPlannerAgent 生成，店长审批后执行"""

    __tablename__ = "daily_plans"

    plan_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="计划ID，格式 PLAN_YYYYMMDD_STOREID",
    )
    store_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="门店ID",
    )
    plan_date: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="计划日期 YYYY-MM-DD",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_approval",
        comment="状态: pending_approval/approved/partial/executing/completed/expired",
    )

    # 五大维度建议（JSON 列表）
    menu_suggestions: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="排菜建议",
    )
    procurement_list: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="采购清单",
    )
    staffing_adjustments: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="排班微调",
    )
    marketing_triggers: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="营销触发",
    )
    risk_alerts: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="风险预警",
    )

    # 审批
    approved_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="审批人",
    )
    approved_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="审批时间",
    )
    approval_notes: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="审批备注（含逐项批/拒）",
    )

    # 执行
    execution_status: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="各项执行状态",
    )
    outcome_summary: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="执行结果摘要",
    )

    # 元数据
    generated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="生成时间",
    )
    summary: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="汇总统计",
    )
