"""R2 三个 Agent 的 ActionParams / ActionResult 契约（R2 新增）

覆盖 Agent：
  reservation_concierge    — 5 actions
  sales_coach              — 6 actions
  banquet_contract_agent   — 5 actions

设计原则：
  - 每个 Agent 的 action 输入/输出模型各一组，Agent 实装时直接 import 本模块
  - 所有金额字段以 _fen 结尾，单位为分（整数）
  - ActionResult 保留 `ok` / `confidence` / `reasoning` / `decision_id`
    用于对齐 CLAUDE.md §9 决策留痕
  - 边缘推理（reservation_concierge 的 identify_caller / confirm_arrival）
    携带 `inference_layer` 字段标注 "edge"
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .banquet_contracts import (
    ApprovalAction,
    ApprovalRole,
    BanquetContract,
    BanquetEOTicket,
    ContractStatus,
    EODepartment,
)
from .banquet_leads import BanquetType, SourceChannel
from .customer_lifecycle import CustomerLifecycleState
from .reservation_invitations import InvitationChannel, InvitationRecord
from .tasks import Task, TaskType

# ═══════════════════════════════════════════════════════════════════════
# reservation_concierge Agent — 5 actions
# ═══════════════════════════════════════════════════════════════════════


class CallerIdentifyParams(BaseModel):
    """identify_caller 参数：根据来电号码返回客户画像卡。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="接听门店ID")
    caller_phone: str = Field(
        ...,
        min_length=4,
        max_length=32,
        description="来电号码（已脱敏或 E.164）",
    )
    call_id: str | None = Field(
        default=None,
        max_length=64,
        description="运营商/外呼平台的通话唯一ID（用于回调回查）",
    )


class CallerProfile(BaseModel):
    """客户画像卡。"""

    customer_id: UUID | None = Field(
        default=None, description="Golden Customer ID（未命中为 None）"
    )
    display_name: str | None = Field(
        default=None, max_length=64, description="客户展示名"
    )
    vip_level: str | None = Field(
        default=None,
        max_length=32,
        description="VIP 等级（如 silver/gold/platinum）",
    )
    lifecycle_state: CustomerLifecycleState | None = Field(
        default=None,
        description="四象限状态（消费 R1 customer_lifecycle_state 表）",
    )
    last_visit_at: datetime | None = Field(
        default=None, description="上次消费时间"
    )
    favorite_dishes: list[str] = Field(
        default_factory=list, description="偏好菜品（Top5）"
    )
    taboo_ingredients: list[str] = Field(
        default_factory=list, description="忌口（过敏/宗教/健康）"
    )
    lifetime_value_fen: int = Field(
        default=0, ge=0, description="累计消费（分）"
    )


class CallerIdentifyResult(BaseModel):
    """identify_caller 返回体。"""

    ok: bool = Field(..., description="是否识别成功")
    profile: CallerProfile | None = Field(
        default=None,
        description="客户画像卡（命中 Golden Customer 时填充）",
    )
    matched_by: str | None = Field(
        default=None,
        description="命中依据：phone / member_card / wechat_openid / none",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="识别置信度"
    )
    reasoning: str = Field(default="", description="决策理由摘要")
    inference_layer: str = Field(
        default="edge",
        description="推理层：edge（Whisper/Core ML）或 cloud",
    )
    decision_id: UUID | None = Field(
        default=None, description="AgentDecisionLog 记录ID"
    )


class SuggestSlotParams(BaseModel):
    """suggest_slot 参数：根据日期+人数+偏好返回可用档期。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID = Field(..., description="目标门店")
    target_date: date = Field(..., description="期望就餐日期")
    guest_count: int = Field(..., ge=1, le=200, description="就餐人数")
    preferred_room_type: str | None = Field(
        default=None,
        max_length=64,
        description="偏好房型（vip_room / big_hall / outdoor 等）",
    )
    customer_id: UUID | None = Field(
        default=None, description="客户ID（用于个性化菜单推荐）"
    )


class SlotOption(BaseModel):
    """单个可用档期。"""

    slot_start: datetime = Field(..., description="档期开始时间")
    slot_end: datetime = Field(..., description="档期结束时间")
    table_type: str = Field(..., description="桌型")
    room_type: str | None = Field(default=None, description="房间类型")
    recommended_package_id: UUID | None = Field(
        default=None, description="推荐套餐ID"
    )
    estimated_amount_fen: int = Field(
        default=0, ge=0, description="预估消费金额（分）"
    )


class SuggestSlotResult(BaseModel):
    """suggest_slot 返回体。"""

    ok: bool = Field(..., description="是否有可用档期")
    options: list[SlotOption] = Field(
        default_factory=list, description="可用档期列表（Top N）"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class DetectCollisionParams(BaseModel):
    """detect_collision 参数：多渠道同客户同日预订的合并检测。"""

    tenant_id: UUID = Field(..., description="租户ID")
    customer_id: UUID = Field(..., description="客户ID")
    target_date: date = Field(..., description="目标日期")
    incoming_reservation_id: UUID = Field(
        ..., description="本次新进入的预订ID"
    )


class CollisionDecision(BaseModel):
    """撞单裁决结果。"""

    is_collision: bool = Field(..., description="是否撞单")
    winning_reservation_id: UUID | None = Field(
        default=None,
        description="保留的预订ID（依优先级裁决）",
    )
    merged_reservation_ids: list[UUID] = Field(
        default_factory=list, description="被合并的预订ID列表"
    )
    priority_channel: SourceChannel | None = Field(
        default=None, description="裁决优先渠道"
    )


class DetectCollisionResult(BaseModel):
    """detect_collision 返回体。"""

    ok: bool = Field(..., description="是否执行成功")
    decision: CollisionDecision = Field(..., description="裁决结果")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class SendInvitationParams(BaseModel):
    """send_invitation 参数：H5 邀请函 + 短信 + 券码联发。"""

    tenant_id: UUID = Field(..., description="租户ID")
    reservation_id: UUID = Field(..., description="预订ID")
    customer_id: UUID | None = Field(default=None, description="客户ID")
    channels: list[InvitationChannel] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="同时触达的通道（通常 sms + wechat）",
    )
    coupon_code: str | None = Field(
        default=None, max_length=64, description="附带券码"
    )
    coupon_value_fen: int = Field(
        default=0, ge=0, description="券面值（分）"
    )
    template_id: str | None = Field(
        default=None, max_length=64, description="模板ID"
    )


class SendInvitationResult(BaseModel):
    """send_invitation 返回体。"""

    ok: bool = Field(..., description="全部通道是否成功")
    invitations: list[InvitationRecord] = Field(
        default_factory=list, description="每通道一条 InvitationRecord"
    )
    failed_channels: list[InvitationChannel] = Field(
        default_factory=list, description="失败通道"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class ConfirmArrivalParams(BaseModel):
    """confirm_arrival 参数：T-2h AI 外呼核餐。"""

    tenant_id: UUID = Field(..., description="租户ID")
    reservation_id: UUID = Field(..., description="预订ID")
    customer_id: UUID | None = Field(default=None, description="客户ID")
    scheduled_at: datetime = Field(
        ..., description="原定到店时间"
    )
    call_script_id: str | None = Field(
        default=None, max_length=64, description="外呼话术脚本ID"
    )


class ConfirmArrivalOutcome(str, Enum):
    """外呼结果。"""

    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    UNREACHABLE = "unreachable"


class ConfirmArrivalResult(BaseModel):
    """confirm_arrival 返回体。"""

    ok: bool = Field(..., description="是否外呼完成（不等同于客户确认）")
    outcome: ConfirmArrivalOutcome = Field(
        ..., description="核餐结果"
    )
    new_scheduled_at: datetime | None = Field(
        default=None,
        description="改期后的新时间（outcome=rescheduled 时必填）",
    )
    transcript_excerpt: str | None = Field(
        default=None,
        max_length=500,
        description="关键对话片段（Whisper 识别）",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    inference_layer: str = Field(
        default="edge",
        description="推理层：edge（Whisper/Core ML）或 cloud",
    )
    decision_id: UUID | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_reschedule(self) -> "ConfirmArrivalResult":
        if (
            self.outcome == ConfirmArrivalOutcome.RESCHEDULED
            and not self.new_scheduled_at
        ):
            raise ValueError("outcome=rescheduled 时 new_scheduled_at 必填")
        return self


# ═══════════════════════════════════════════════════════════════════════
# sales_coach Agent — 6 actions
# ═══════════════════════════════════════════════════════════════════════


class DecomposeTargetParams(BaseModel):
    """decompose_target 参数：年目标 → 月/周/日分解。"""

    tenant_id: UUID = Field(..., description="租户ID")
    year_target_id: UUID = Field(
        ..., description="年度目标ID（sales_targets.target_id）"
    )
    decompose_to: list[str] = Field(
        default_factory=lambda: ["month", "week", "day"],
        description="分解到的粒度组合",
    )


class DecomposeTargetResult(BaseModel):
    """decompose_target 返回体。"""

    ok: bool = Field(..., description="是否成功分解")
    generated_target_ids: list[UUID] = Field(
        default_factory=list, description="生成的子目标ID列表"
    )
    total_parent_value: int = Field(
        default=0, ge=0, description="父目标合计（分/计数）"
    )
    total_children_value: int = Field(
        default=0,
        ge=0,
        description="子目标合计（应等于父目标，允许 <=0.01% 误差）",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class DispatchDailyTasksParams(BaseModel):
    """dispatch_daily_tasks 参数：每日定时自动派发 10 类任务。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="门店ID")
    employee_id: UUID | None = Field(
        default=None, description="销售员工（为空则派全店）"
    )
    plan_date: date = Field(..., description="派单目标日期")
    task_types: list[TaskType] = Field(
        default_factory=list,
        description="限定派发的任务类型（空表示全部 10 类）",
    )


class DispatchDailyTasksResult(BaseModel):
    """dispatch_daily_tasks 返回体。"""

    ok: bool = Field(..., description="是否派发完成")
    dispatched_tasks: list[Task] = Field(
        default_factory=list, description="本次派发的任务列表"
    )
    dispatched_count_by_type: dict[str, int] = Field(
        default_factory=dict, description="按 task_type 计数"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class DiagnoseGapParams(BaseModel):
    """diagnose_gap 参数：偏差 > 15% 时给出诊断建议。"""

    tenant_id: UUID = Field(..., description="租户ID")
    target_id: UUID = Field(..., description="目标ID")
    snapshot_at: datetime = Field(..., description="快照时间")
    gap_threshold: Decimal = Field(
        default=Decimal("0.15"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="偏差告警阈值（默认 15%）",
    )


class GapRemediation(BaseModel):
    """诊断建议。"""

    kind: str = Field(
        ...,
        description="建议类别：call_customers / push_recall_campaign / reassign_leads",
    )
    suggested_call_count: int = Field(
        default=0, ge=0, description="建议电话数量"
    )
    suggested_customer_ids: list[UUID] = Field(
        default_factory=list, description="建议主攻客户"
    )
    expected_recovery_fen: int = Field(
        default=0, ge=0, description="预期回补金额（分）"
    )


class DiagnoseGapResult(BaseModel):
    """diagnose_gap 返回体。"""

    ok: bool = Field(..., description="是否诊断完成")
    has_gap: bool = Field(..., description="是否触发偏差告警")
    achievement_rate: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("9.9999"),
        description="当前达成率",
    )
    remediations: list[GapRemediation] = Field(
        default_factory=list, description="诊断建议列表"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class CoachActionParams(BaseModel):
    """coach_action 参数：生成个性化教练建议。"""

    tenant_id: UUID = Field(..., description="租户ID")
    employee_id: UUID = Field(..., description="目标销售员工")
    focus: str = Field(
        default="auto",
        description="主攻方向：auto / dormant / new_customer / high_value",
    )


class CoachingAdvice(BaseModel):
    """教练建议项。"""

    topic: str = Field(..., description="主题标签")
    priority: str = Field(
        default="normal",
        description="优先级：low/normal/high",
    )
    message: str = Field(
        ..., max_length=500, description="建议内容（自然语言）"
    )


class CoachActionResult(BaseModel):
    """coach_action 返回体。"""

    ok: bool = Field(..., description="是否生成建议")
    advice: list[CoachingAdvice] = Field(
        default_factory=list, description="建议列表"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class AuditCoverageParams(BaseModel):
    """audit_coverage 参数：检测资源分布与 VIP 维护。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="门店ID")
    dormant_ratio_alert: Decimal = Field(
        default=Decimal("0.40"),
        description="沉睡占比告警阈值（默认 40%）",
    )


class AuditCoverageResult(BaseModel):
    """audit_coverage 返回体。"""

    ok: bool = Field(..., description="是否扫描完成")
    dormant_ratio: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="当前沉睡占比",
    )
    dormant_alert: bool = Field(..., description="是否超过阈值告警")
    unmaintained_vip_count: int = Field(
        default=0, ge=0, description="未维护 VIP 数量"
    )
    unmaintained_vip_ids: list[UUID] = Field(
        default_factory=list, description="未维护 VIP ID 列表"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class ProfileCompletenessParams(BaseModel):
    """score_profile_completeness 参数：8 字段加权评分。"""

    tenant_id: UUID = Field(..., description="租户ID")
    employee_id: UUID | None = Field(
        default=None,
        description="限定员工（为空扫全店）",
    )
    alert_threshold: Decimal = Field(
        default=Decimal("0.50"),
        description="低于阈值触发补录任务（默认 50%）",
    )


class ProfileScoreEntry(BaseModel):
    """单员工得分。"""

    employee_id: UUID = Field(..., description="员工ID")
    customer_count: int = Field(default=0, ge=0)
    average_score: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="平均完整度（0-1）",
    )
    below_threshold_customer_ids: list[UUID] = Field(
        default_factory=list,
        description="低于阈值的客户ID（触发补录任务）",
    )


class ProfileCompletenessResult(BaseModel):
    """score_profile_completeness 返回体。"""

    ok: bool = Field(..., description="是否评分完成")
    scores: list[ProfileScoreEntry] = Field(
        default_factory=list, description="按员工聚合得分"
    )
    dispatched_task_count: int = Field(
        default=0, ge=0, description="触发补录任务数量"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════
# banquet_contract_agent — 5 actions
# ═══════════════════════════════════════════════════════════════════════


class GenerateContractParams(BaseModel):
    """generate_contract 参数：按商机 + 套餐 + 订金比例生成 PDF 合同。"""

    tenant_id: UUID = Field(..., description="租户ID")
    lead_id: UUID = Field(..., description="商机ID")
    customer_id: UUID = Field(..., description="客户ID")
    sales_employee_id: UUID | None = Field(
        default=None, description="销售员工ID"
    )
    banquet_type: BanquetType = Field(..., description="宴会类型")
    tables: int = Field(..., ge=1, le=500, description="桌数")
    total_amount_fen: int = Field(..., ge=0, description="合同总金额（分）")
    deposit_ratio: Decimal = Field(
        default=Decimal("0.30"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="订金比例（默认 30%）",
    )
    scheduled_date: date | None = Field(
        default=None, description="预定宴会日期"
    )
    template_id: str | None = Field(
        default=None, max_length=64, description="PDF 模板ID"
    )


class GenerateContractResult(BaseModel):
    """generate_contract 返回体。"""

    ok: bool = Field(..., description="是否成功生成")
    contract: BanquetContract | None = Field(
        default=None, description="生成的合同记录"
    )
    pdf_url: str | None = Field(
        default=None, max_length=500, description="PDF 地址"
    )
    generation_ms: int = Field(
        default=0, ge=0, description="PDF 生成耗时（毫秒）"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class SplitEOParams(BaseModel):
    """split_eo 参数：合同拆分为 5 部门 EO 工单。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    departments: list[EODepartment] = Field(
        default_factory=lambda: [
            EODepartment.KITCHEN,
            EODepartment.HALL,
            EODepartment.PURCHASE,
            EODepartment.FINANCE,
            EODepartment.MARKETING,
        ],
        description="要拆分的部门（默认 5 个全拆）",
    )


class SplitEOResult(BaseModel):
    """split_eo 返回体。"""

    ok: bool = Field(..., description="是否成功拆分")
    tickets: list[BanquetEOTicket] = Field(
        default_factory=list, description="生成的 EO 工单列表"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class RouteApprovalParams(BaseModel):
    """route_approval 参数：按金额/类型决定审批链。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    total_amount_fen: int = Field(..., ge=0, description="合同总金额（分）")
    banquet_type: BanquetType = Field(..., description="宴会类型")
    approver_id: UUID | None = Field(
        default=None,
        description="指定审批人（为空由规则自动路由）",
    )
    approval_action: ApprovalAction | None = Field(
        default=None,
        description="审批动作（首次路由为 None，再次调用时填写决策）",
    )
    notes: str | None = Field(
        default=None, max_length=500, description="审批备注"
    )


class RouteApprovalResult(BaseModel):
    """route_approval 返回体。"""

    ok: bool = Field(..., description="是否路由/审批成功")
    next_role: ApprovalRole | None = Field(
        default=None,
        description="下一审批角色（None 表示审批链结束）",
    )
    final_status: ContractStatus = Field(
        ..., description="合同当前状态"
    )
    auto_passed: bool = Field(
        default=False,
        description="是否自动过（金额 < 10W 且非婚宴）",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class LockScheduleParams(BaseModel):
    """lock_schedule 参数：首交订金锁定档期。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    scheduled_date: date = Field(..., description="锁定日期")
    store_id: UUID = Field(..., description="门店ID")
    deposit_paid_fen: int = Field(
        ..., ge=0, description="已支付订金（分）"
    )


class LockScheduleResult(BaseModel):
    """lock_schedule 返回体。"""

    ok: bool = Field(..., description="是否成功锁定档期")
    locked: bool = Field(..., description="本次调用是否获得档期")
    queued_contract_ids: list[UUID] = Field(
        default_factory=list,
        description="同日候补合同ID列表（FIFO 顺序）",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


class ProgressReminderParams(BaseModel):
    """progress_reminder 参数：T-7d/T-3d/T-1d/T-2h 四级推送。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    reminder_stage: str = Field(
        ...,
        description="提醒阶段：T-7d / T-3d / T-1d / T-2h",
    )
    target_departments: list[EODepartment] = Field(
        default_factory=list,
        description="目标部门（空表示全部 5 部门）",
    )


class ProgressReminderResult(BaseModel):
    """progress_reminder 返回体。"""

    ok: bool = Field(..., description="是否成功推送")
    notified_ticket_ids: list[UUID] = Field(
        default_factory=list, description="被通知的 EO 工单ID"
    )
    skipped_reason: str | None = Field(
        default=None,
        max_length=200,
        description="未推送原因（如工单已完成）",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    decision_id: UUID | None = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════
# 决策留痕 — 对齐 CLAUDE.md §9
# ═══════════════════════════════════════════════════════════════════════


class AgentDecisionLogRecord(BaseModel):
    """AgentDecisionLog 契约（R2 三 Agent 决策留痕共用结构）。"""

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(..., description="决策记录唯一ID")
    tenant_id: UUID = Field(..., description="租户ID")
    agent_id: str = Field(
        ...,
        description="Agent ID（reservation_concierge/sales_coach/banquet_contract_agent）",
    )
    action: str = Field(..., description="触发的 action 名")
    decision_type: str = Field(
        ...,
        description="决策分类：suggest / auto / fully_autonomous",
    )
    input_context: dict[str, Any] = Field(
        default_factory=dict, description="输入上下文快照"
    )
    reasoning: str = Field(default="", description="推理过程摘要")
    output_action: dict[str, Any] = Field(
        default_factory=dict, description="输出动作快照"
    )
    constraints_check: dict[str, Any] = Field(
        default_factory=dict,
        description="三条硬约束校验结果：margin/safety/experience",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="置信度"
    )
    inference_layer: str = Field(
        default="cloud", description="推理层：edge/cloud"
    )
    created_at: datetime = Field(..., description="创建时间")
