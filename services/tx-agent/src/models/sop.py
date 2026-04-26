"""SOP时间轴引擎 — Phase S1 全部6个ORM模型

表：sop_templates / sop_time_slots / sop_tasks /
    sop_task_instances / sop_corrective_actions / sop_store_configs
"""
import uuid
from datetime import date, datetime, time
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, Text, Time
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────
# sop_templates — SOP模板（品牌级定义）
# ─────────────────────────────────────────────
class SOPTemplate(TenantBase):
    """SOP模板 — 按业态(full_service/qsr/hotpot/bakery)定义的标准流程"""

    __tablename__ = "sop_templates"

    template_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="模板名称，如'标准正餐店SOP'",
    )
    store_format: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="业态：full_service / qsr / hotpot / bakery",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="是否为该业态的默认模板",
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="模板版本号",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="模板描述",
    )

    # ── 关系 ──
    time_slots: Mapped[List["SOPTimeSlot"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tasks: Mapped[List["SOPTask"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    store_configs: Mapped[List["SOPStoreConfig"]] = relationship(
        back_populates="template",
        lazy="selectin",
    )


# ─────────────────────────────────────────────
# sop_time_slots — 时段定义
# ─────────────────────────────────────────────
class SOPTimeSlot(TenantBase):
    """SOP时段 — 模板级时间段划分（如午市高峰、晚市备餐）"""

    __tablename__ = "sop_time_slots"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="所属模板ID",
    )
    slot_code: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="时段代码：morning_prep / morning_brief / lunch_buildup / "
                "lunch_peak / afternoon_lull / dinner_buildup / dinner_peak / closing",
    )
    slot_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="时段显示名，如'午市高峰'",
    )
    start_time: Mapped[time] = mapped_column(
        Time, nullable=False, comment="开始时间",
    )
    end_time: Mapped[time] = mapped_column(
        Time, nullable=False, comment="结束时间",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="排序序号",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用",
    )

    # ── 关系 ──
    template: Mapped["SOPTemplate"] = relationship(
        back_populates="time_slots",
    )
    tasks: Mapped[List["SOPTask"]] = relationship(
        back_populates="time_slot",
        lazy="selectin",
    )


# ─────────────────────────────────────────────
# sop_tasks — SOP任务定义（模板级）
# ─────────────────────────────────────────────
class SOPTask(TenantBase):
    """SOP任务定义 — 模板级，绑定时段和角色"""

    __tablename__ = "sop_tasks"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="所属模板ID",
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="所属时段ID",
    )
    task_code: Mapped[str] = mapped_column(
        Text, nullable=False, comment="任务代码（唯一标识）",
    )
    task_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="任务显示名",
    )
    task_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="任务类型：checklist / inspection / report / action",
    )
    target_role: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="目标角色：store_manager / kitchen_lead / floor_lead / cashier / all",
    )
    priority: Mapped[str] = mapped_column(
        Text, default="normal", server_default="normal",
        comment="优先级：critical / high / normal / low",
    )
    duration_min: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="预计耗时（分钟）",
    )
    instructions: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="操作说明",
    )
    checklist_items: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment='检查项列表，如 [{"item": "检查冰箱温度", "required": true}]',
    )
    condition_logic: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="条件逻辑 JSON，定义任务触发条件",
    )
    auto_complete: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment='自动完成规则，如 {"source": "pos_data", "condition": "revenue > 0"}',
    )
    data_source: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="数据来源标识",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="排序序号",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用",
    )

    # ── 关系 ──
    template: Mapped["SOPTemplate"] = relationship(
        back_populates="tasks",
    )
    time_slot: Mapped["SOPTimeSlot"] = relationship(
        back_populates="tasks",
    )
    instances: Mapped[List["SOPTaskInstance"]] = relationship(
        back_populates="task",
        lazy="selectin",
    )


# ─────────────────────────────────────────────
# sop_task_instances — SOP任务实例（门店级执行记录）
# ─────────────────────────────────────────────
class SOPTaskInstance(TenantBase):
    """SOP任务实例 — 门店级每日执行记录"""

    __tablename__ = "sop_task_instances"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="任务定义ID",
    )
    instance_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="执行日期",
    )
    slot_code: Mapped[str] = mapped_column(
        Text, nullable=False, comment="时段代码（冗余，便于查询）",
    )
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="指派人ID",
    )
    target_role: Mapped[str] = mapped_column(
        Text, nullable=False, comment="目标角色",
    )
    status: Mapped[str] = mapped_column(
        Text, default="pending", server_default="pending",
        comment="状态：pending / in_progress / completed / overdue / skipped / auto_completed",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="开始时间",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间",
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="截止时间",
    )
    result: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="执行结果 JSON",
    )
    compliance: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="合规结果：pass / fail / warning",
    )
    ai_suggestion: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Agent生成的智能建议",
    )

    # ── 关系 ──
    task: Mapped["SOPTask"] = relationship(
        back_populates="instances",
    )
    corrective_actions: Mapped[List["SOPCorrectiveAction"]] = relationship(
        back_populates="source_instance",
        lazy="selectin",
    )


# ─────────────────────────────────────────────
# sop_corrective_actions — 纠正动作链
# ─────────────────────────────────────────────
class SOPCorrectiveAction(TenantBase):
    """SOP纠正动作 — 任务不合规时的跟踪闭环"""

    __tablename__ = "sop_corrective_actions"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    source_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="来源任务实例ID",
    )
    action_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="动作类型：immediate / follow_up / escalation",
    )
    severity: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="严重程度：critical / warning / info",
    )
    title: Mapped[str] = mapped_column(
        Text, nullable=False, comment="纠正动作标题",
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="纠正动作详细描述",
    )
    assignee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="责任人ID",
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="截止时间",
    )
    status: Mapped[str] = mapped_column(
        Text, default="open", server_default="open",
        comment="状态：open / in_progress / resolved / verified / escalated",
    )
    resolution: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="解决方案 JSON",
    )
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="验证人ID",
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="验证时间",
    )
    escalated_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="升级目标人ID",
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="升级时间",
    )

    # ── 关系 ──
    source_instance: Mapped["SOPTaskInstance"] = relationship(
        back_populates="corrective_actions",
    )


# ─────────────────────────────────────────────
# sop_store_configs — 门店SOP配置
# ─────────────────────────────────────────────
class SOPStoreConfig(TenantBase):
    """门店SOP配置 — 门店绑定SOP模板 + 时区 + 自定义覆盖"""

    __tablename__ = "sop_store_configs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="绑定的SOP模板ID",
    )
    timezone: Mapped[str] = mapped_column(
        Text, default="Asia/Shanghai", server_default="Asia/Shanghai",
        comment="门店时区",
    )
    custom_overrides: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="自定义覆盖 JSON，可覆盖模板中的时段/任务配置",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用",
    )

    # ── 关系 ──
    template: Mapped["SOPTemplate"] = relationship(
        back_populates="store_configs",
    )
