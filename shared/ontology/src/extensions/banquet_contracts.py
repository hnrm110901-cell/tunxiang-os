"""宴会合同 / EO 工单 / 审批日志契约（R2 新增）

对应迁移：v282_banquet_contracts
对应事件：shared.events.event_types.BanquetContractEventType

合同状态（status）：
  draft             — 起草（PDF 未生成或未签）
  pending_approval  — 等待审批（总额 ≥10W 触发店长，≥50W 追加区经）
  signed            — 已签约（档期锁定，EO 可分发）
  cancelled         — 作废（需填写 cancellation_reason）

EO 工单部门：
  kitchen / hall / purchase / finance / marketing

EO 状态：
  pending → dispatched → in_progress → completed

审批角色：
  store_manager / district_manager / finance_manager

金额字段以 _fen 结尾，单位为分（整数）。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 复用 R1 已定义的宴会类型枚举（避免重复定义）
from .banquet_leads import BanquetType


class ContractStatus(str, Enum):
    """合同状态机。"""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    SIGNED = "signed"
    CANCELLED = "cancelled"


class EOTicketStatus(str, Enum):
    """EO 工单状态机。"""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class EODepartment(str, Enum):
    """EO 工单部门。"""

    KITCHEN = "kitchen"
    HALL = "hall"
    PURCHASE = "purchase"
    FINANCE = "finance"
    MARKETING = "marketing"


class ApprovalAction(str, Enum):
    """审批动作。"""

    APPROVE = "approve"
    REJECT = "reject"


class ApprovalRole(str, Enum):
    """审批角色。"""

    STORE_MANAGER = "store_manager"
    DISTRICT_MANAGER = "district_manager"
    FINANCE_MANAGER = "finance_manager"


# ─────────────────────────────────────────────────────────────────
# banquet_contracts 表契约
# ─────────────────────────────────────────────────────────────────


class BanquetContract(BaseModel):
    """banquet_contracts 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    contract_id: UUID = Field(..., description="合同唯一ID")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    store_id: UUID | None = Field(default=None, description="归属门店ID")
    lead_id: UUID = Field(
        ...,
        description="对应 banquet_leads.lead_id（跨服务弱耦合，不加 FK）",
    )
    customer_id: UUID = Field(..., description="客户ID")
    sales_employee_id: UUID | None = Field(
        default=None, description="跟进销售员工ID"
    )
    banquet_type: BanquetType = Field(..., description="宴会类型（复用 R1 枚举）")
    tables: int = Field(default=0, ge=0, description="桌数")
    total_amount_fen: int = Field(
        default=0, ge=0, description="合同总金额（分/整数）"
    )
    deposit_fen: int = Field(
        default=0,
        ge=0,
        description="订金（分/整数，必须 <= total_amount_fen）",
    )
    pdf_url: str | None = Field(
        default=None,
        max_length=500,
        description="合同 PDF 存储地址（对象存储 URL）",
    )
    status: ContractStatus = Field(
        default=ContractStatus.DRAFT,
        description="合同状态",
    )
    approval_chain: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "审批链快照："
            "[{role, approver_id, required_threshold_fen, decided_action?, decided_at?}]"
        ),
    )
    scheduled_date: date | None = Field(
        default=None, description="预定宴会日期"
    )
    signed_at: datetime | None = Field(
        default=None,
        description="签约时间（status=signed 时必填）",
    )
    cancelled_at: datetime | None = Field(
        default=None,
        description="作废时间（status=cancelled 时必填）",
    )
    cancellation_reason: str | None = Field(
        default=None,
        max_length=200,
        description="作废原因（status=cancelled 时必填）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据 JSON"
    )
    created_by: UUID | None = Field(
        default=None, description="创建人员工ID"
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

    @model_validator(mode="after")
    def _validate_status(self) -> "BanquetContract":
        if self.deposit_fen > self.total_amount_fen:
            raise ValueError("deposit_fen 不能超过 total_amount_fen")
        if self.status == ContractStatus.SIGNED and not self.signed_at:
            raise ValueError("status=signed 时 signed_at 必填")
        if self.status == ContractStatus.CANCELLED:
            if not self.cancelled_at:
                raise ValueError("status=cancelled 时 cancelled_at 必填")
            if not self.cancellation_reason:
                raise ValueError("status=cancelled 时 cancellation_reason 必填")
        return self


class BanquetContractCreateRequest(BaseModel):
    """合同创建请求契约（generate_contract action 使用）。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="门店ID")
    lead_id: UUID = Field(..., description="关联商机ID")
    customer_id: UUID = Field(..., description="客户ID")
    sales_employee_id: UUID | None = Field(
        default=None, description="销售员工ID"
    )
    banquet_type: BanquetType = Field(..., description="宴会类型")
    tables: int = Field(default=0, ge=0, description="桌数")
    total_amount_fen: int = Field(
        ..., ge=0, description="合同总金额（分）"
    )
    deposit_fen: int = Field(
        default=0, ge=0, description="订金（分）"
    )
    scheduled_date: date | None = Field(
        default=None, description="预定宴会日期"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据"
    )

    @model_validator(mode="after")
    def _validate_deposit(self) -> "BanquetContractCreateRequest":
        if self.deposit_fen > self.total_amount_fen:
            raise ValueError("deposit_fen 不能超过 total_amount_fen")
        return self


# ─────────────────────────────────────────────────────────────────
# banquet_eo_tickets 表契约
# ─────────────────────────────────────────────────────────────────


class BanquetEOTicket(BaseModel):
    """banquet_eo_tickets 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    eo_ticket_id: UUID = Field(..., description="EO 工单唯一ID")
    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(
        ...,
        description="所属合同ID（FK → banquet_contracts.contract_id，CASCADE）",
    )
    department: EODepartment = Field(..., description="部门")
    assignee_employee_id: UUID | None = Field(
        default=None, description="部门内责任人"
    )
    content: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "部门专用内容 JSON："
            "kitchen 菜单 / hall 订台 / purchase 物料 / finance 账单 / marketing 物料"
        ),
    )
    status: EOTicketStatus = Field(
        default=EOTicketStatus.PENDING, description="工单状态"
    )
    dispatched_at: datetime | None = Field(
        default=None,
        description="分发时间（status=dispatched 时必填）",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="完成时间（status=completed 时必填）",
    )
    reminder_sent_at: datetime | None = Field(
        default=None, description="最近一次提醒推送时间"
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

    @model_validator(mode="after")
    def _validate_status(self) -> "BanquetEOTicket":
        if (
            self.status == EOTicketStatus.DISPATCHED
            and not self.dispatched_at
        ):
            raise ValueError("status=dispatched 时 dispatched_at 必填")
        if (
            self.status == EOTicketStatus.COMPLETED
            and not self.completed_at
        ):
            raise ValueError("status=completed 时 completed_at 必填")
        return self


class BanquetEODispatchRequest(BaseModel):
    """EO 工单派发请求契约（split_eo action 使用，一次可派 5 部门）。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    departments: list[EODepartment] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="一次派发的部门集合（通常 5 个全派）",
    )
    content_by_department: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="每个部门的内容 JSON（key=department 枚举 value）",
    )


# ─────────────────────────────────────────────────────────────────
# banquet_approval_logs 表契约
# ─────────────────────────────────────────────────────────────────


class BanquetApprovalLog(BaseModel):
    """banquet_approval_logs 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    log_id: UUID = Field(..., description="审批日志唯一ID")
    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(
        ...,
        description="被审批的合同ID（FK → banquet_contracts，CASCADE）",
    )
    approver_id: UUID = Field(..., description="审批人员工ID")
    role: ApprovalRole = Field(..., description="审批角色")
    action: ApprovalAction = Field(..., description="approve/reject")
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="审批备注（action=reject 时必填）",
    )
    source_event_id: UUID | None = Field(
        default=None, description="触发事件ID（可选）"
    )
    created_at: datetime = Field(..., description="创建时间")

    @model_validator(mode="after")
    def _validate_reject_notes(self) -> "BanquetApprovalLog":
        if self.action == ApprovalAction.REJECT and not self.notes:
            raise ValueError("action=reject 时 notes 必填")
        return self


class BanquetApprovalRouteRequest(BaseModel):
    """审批路由请求契约（route_approval action 使用）。"""

    tenant_id: UUID = Field(..., description="租户ID")
    contract_id: UUID = Field(..., description="合同ID")
    approver_id: UUID = Field(..., description="审批人")
    role: ApprovalRole = Field(..., description="审批角色")
    action: ApprovalAction = Field(..., description="approve/reject")
    notes: str | None = Field(
        default=None, max_length=500, description="审批备注"
    )

    @model_validator(mode="after")
    def _validate_reject(self) -> "BanquetApprovalRouteRequest":
        if self.action == ApprovalAction.REJECT and not self.notes:
            raise ValueError("action=reject 时 notes 必填")
        return self
