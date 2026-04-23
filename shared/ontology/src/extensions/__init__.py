"""屯象 Ontology 扩展包（Pydantic 契约层）

按 CLAUDE.md §18 Ontology 冻结规则：
  shared/ontology/src/ 下的 SQLAlchemy Ontology（entities.py / base.py / enums.py）
  禁止自动修改；新业务的扩展契约（预订/任务/目标/宴会商机等）统一归入
  `extensions/` 子目录，以 Pydantic model 表达，供 API/Agent/投影器共用。

扩展层特征：
  - 纯 Pydantic V2，无 SQLAlchemy 依赖
  - 金额字段必须以 `_fen` 结尾且为 int
  - 所有字段必须带 Field(description=...)
  - 不持久化 Session / ORM 行为，只做契约描述

当前模块（Sprint R1 + R2）：
  # Sprint R1 — 数据底座
  customer_lifecycle       — 客户四象限状态机
  tasks                    — 10 类任务引擎
  sales_targets            — 年/月/周/日销售目标
  banquet_leads            — 宴会商机漏斗

  # Sprint R2 — 3 Agent 契约
  reservation_invitations  — 邀请函 / 核餐外呼记录
  banquet_contracts        — 宴会合同 / EO 工单 / 审批日志
  agent_actions            — 3 个新 Agent 的 ActionParams / ActionResult
"""

from .agent_actions import (
    AgentDecisionLogRecord,
    AuditCoverageParams,
    AuditCoverageResult,
    CallerIdentifyParams,
    CallerIdentifyResult,
    CallerProfile,
    CoachActionParams,
    CoachActionResult,
    CoachingAdvice,
    CollisionDecision,
    ConfirmArrivalOutcome,
    ConfirmArrivalParams,
    ConfirmArrivalResult,
    DecomposeTargetParams,
    DecomposeTargetResult,
    DetectCollisionParams,
    DetectCollisionResult,
    DiagnoseGapParams,
    DiagnoseGapResult,
    DispatchDailyTasksParams,
    DispatchDailyTasksResult,
    GapRemediation,
    GenerateContractParams,
    GenerateContractResult,
    LockScheduleParams,
    LockScheduleResult,
    ProfileCompletenessParams,
    ProfileCompletenessResult,
    ProfileScoreEntry,
    ProgressReminderParams,
    ProgressReminderResult,
    RouteApprovalParams,
    RouteApprovalResult,
    SendInvitationParams,
    SendInvitationResult,
    SlotOption,
    SplitEOParams,
    SplitEOResult,
    SuggestSlotParams,
    SuggestSlotResult,
)
from .banquet_contracts import (
    ApprovalAction,
    ApprovalRole,
    BanquetApprovalLog,
    BanquetApprovalRouteRequest,
    BanquetContract,
    BanquetContractCreateRequest,
    BanquetEODispatchRequest,
    BanquetEOTicket,
    ContractStatus,
    EODepartment,
    EOTicketStatus,
)
from .banquet_leads import (
    BanquetLead,
    BanquetLeadCreateRequest,
    BanquetLeadStageChangeRequest,
    BanquetType,
    LeadStage,
    SourceChannel,
)
from .customer_lifecycle import (
    CustomerLifecycleRecord,
    CustomerLifecycleState,
    CustomerLifecycleTransitionRequest,
)
from .reservation_invitations import (
    InvitationChannel,
    InvitationCreateRequest,
    InvitationRecord,
    InvitationStatus,
    InvitationUpdateRequest,
)
from .sales_targets import (
    MetricType,
    PeriodType,
    SalesProgress,
    SalesTarget,
    SalesTargetCreateRequest,
)
from .tasks import (
    Task,
    TaskDispatchRequest,
    TaskDispatchResponse,
    TaskStatus,
    TaskType,
)

__all__ = [
    # ── R1 ──
    # customer_lifecycle
    "CustomerLifecycleState",
    "CustomerLifecycleRecord",
    "CustomerLifecycleTransitionRequest",
    # tasks
    "TaskType",
    "TaskStatus",
    "Task",
    "TaskDispatchRequest",
    "TaskDispatchResponse",
    # sales_targets
    "PeriodType",
    "MetricType",
    "SalesTarget",
    "SalesProgress",
    "SalesTargetCreateRequest",
    # banquet_leads
    "BanquetType",
    "SourceChannel",
    "LeadStage",
    "BanquetLead",
    "BanquetLeadCreateRequest",
    "BanquetLeadStageChangeRequest",
    # ── R2 ──
    # reservation_invitations
    "InvitationChannel",
    "InvitationStatus",
    "InvitationRecord",
    "InvitationCreateRequest",
    "InvitationUpdateRequest",
    # banquet_contracts
    "ContractStatus",
    "EOTicketStatus",
    "EODepartment",
    "ApprovalAction",
    "ApprovalRole",
    "BanquetContract",
    "BanquetContractCreateRequest",
    "BanquetEOTicket",
    "BanquetEODispatchRequest",
    "BanquetApprovalLog",
    "BanquetApprovalRouteRequest",
    # agent_actions — reservation_concierge
    "CallerIdentifyParams",
    "CallerProfile",
    "CallerIdentifyResult",
    "SuggestSlotParams",
    "SlotOption",
    "SuggestSlotResult",
    "DetectCollisionParams",
    "CollisionDecision",
    "DetectCollisionResult",
    "SendInvitationParams",
    "SendInvitationResult",
    "ConfirmArrivalParams",
    "ConfirmArrivalOutcome",
    "ConfirmArrivalResult",
    # agent_actions — sales_coach
    "DecomposeTargetParams",
    "DecomposeTargetResult",
    "DispatchDailyTasksParams",
    "DispatchDailyTasksResult",
    "DiagnoseGapParams",
    "GapRemediation",
    "DiagnoseGapResult",
    "CoachActionParams",
    "CoachingAdvice",
    "CoachActionResult",
    "AuditCoverageParams",
    "AuditCoverageResult",
    "ProfileCompletenessParams",
    "ProfileScoreEntry",
    "ProfileCompletenessResult",
    # agent_actions — banquet_contract_agent
    "GenerateContractParams",
    "GenerateContractResult",
    "SplitEOParams",
    "SplitEOResult",
    "RouteApprovalParams",
    "RouteApprovalResult",
    "LockScheduleParams",
    "LockScheduleResult",
    "ProgressReminderParams",
    "ProgressReminderResult",
    # 决策留痕
    "AgentDecisionLogRecord",
]
