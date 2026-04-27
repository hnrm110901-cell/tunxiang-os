"""宴会商机漏斗契约 — 全部商机→商机→订单→失效（R1 新增）

对应迁移：v267_banquet_leads
对应事件：shared.events.event_types.BanquetLeadEventType

宴会类型（对标食尚订 §4-§6）：
  wedding / birthday / corporate / baby_banquet / reunion / graduation

渠道来源：
  booking_desk / referral / hunliji / dianping / internal /
  meituan / gaode / baidu

漏斗阶段：
  all         — 所有商机（初始进入）
  opportunity — 有明确意向
  order       — 正式下订金/合同
  invalid     — 失效（需填 invalidation_reason）

金额字段以 _fen 结尾，单位为分（整数）。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BanquetType(str, Enum):
    """宴会业务类型。"""

    WEDDING = "wedding"
    BIRTHDAY = "birthday"
    CORPORATE = "corporate"
    BABY_BANQUET = "baby_banquet"
    REUNION = "reunion"
    GRADUATION = "graduation"


class SourceChannel(str, Enum):
    """商机渠道来源。"""

    BOOKING_DESK = "booking_desk"
    REFERRAL = "referral"
    HUNLIJI = "hunliji"
    DIANPING = "dianping"
    INTERNAL = "internal"
    MEITUAN = "meituan"
    GAODE = "gaode"
    BAIDU = "baidu"


class LeadStage(str, Enum):
    """商机漏斗阶段。"""

    ALL = "all"
    OPPORTUNITY = "opportunity"
    ORDER = "order"
    INVALID = "invalid"


class BanquetLead(BaseModel):
    """banquet_leads 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    lead_id: UUID = Field(..., description="商机唯一ID")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    store_id: UUID | None = Field(
        default=None,
        description="归属门店ID（集团商机可为空）",
    )
    customer_id: UUID = Field(
        ...,
        description="客户ID（Golden Customer）",
    )
    sales_employee_id: UUID | None = Field(
        default=None,
        description="跟进销售员工ID（可暂缺，待分派）",
    )
    banquet_type: BanquetType = Field(..., description="宴会类型")
    source_channel: SourceChannel = Field(
        default=SourceChannel.BOOKING_DESK,
        description="渠道来源",
    )
    stage: LeadStage = Field(
        default=LeadStage.ALL,
        description="当前漏斗阶段",
    )
    estimated_amount_fen: int = Field(
        default=0,
        ge=0,
        description="预估金额（分/整数）",
    )
    estimated_tables: int = Field(
        default=0,
        ge=0,
        description="预估桌数",
    )
    scheduled_date: date | None = Field(
        default=None,
        description="预计宴会日期",
    )
    stage_changed_at: datetime = Field(
        ...,
        description="最近一次阶段变更时间",
    )
    previous_stage: LeadStage | None = Field(
        default=None,
        description="上一阶段（用于漏斗时长分析）",
    )
    invalidation_reason: str | None = Field(
        default=None,
        max_length=200,
        description="失效原因（stage=invalid 时必填）",
    )
    converted_reservation_id: UUID | None = Field(
        default=None,
        description="转正式预订后的 reservation_id（stage=order 时写入）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据 JSON",
    )
    created_by: UUID | None = Field(
        default=None,
        description="创建人员工ID",
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

    @model_validator(mode="after")
    def _validate_invalid_reason(self) -> "BanquetLead":
        if self.stage == LeadStage.INVALID and not self.invalidation_reason:
            raise ValueError("stage=invalid 时 invalidation_reason 必填")
        return self


class BanquetLeadCreateRequest(BaseModel):
    """商机创建请求契约。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="归属门店ID")
    customer_id: UUID = Field(..., description="客户ID")
    sales_employee_id: UUID | None = Field(
        default=None,
        description="跟进销售员工ID",
    )
    banquet_type: BanquetType = Field(..., description="宴会类型")
    source_channel: SourceChannel = Field(
        default=SourceChannel.BOOKING_DESK,
        description="渠道来源",
    )
    estimated_amount_fen: int = Field(
        default=0,
        ge=0,
        description="预估金额（分）",
    )
    estimated_tables: int = Field(
        default=0,
        ge=0,
        description="预估桌数",
    )
    scheduled_date: date | None = Field(
        default=None,
        description="预计宴会日期",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据 JSON",
    )


class BanquetLeadStageChangeRequest(BaseModel):
    """商机阶段变更请求契约。"""

    lead_id: UUID = Field(..., description="商机ID")
    tenant_id: UUID = Field(..., description="租户ID")
    target_stage: LeadStage = Field(..., description="目标阶段")
    invalidation_reason: str | None = Field(
        default=None,
        max_length=200,
        description="失效原因（target_stage=invalid 时必填）",
    )
    converted_reservation_id: UUID | None = Field(
        default=None,
        description="关联预订ID（target_stage=order 时写入）",
    )
    operator_employee_id: UUID | None = Field(
        default=None,
        description="操作人员工ID（用于审计留痕）",
    )

    @model_validator(mode="after")
    def _validate_transition(self) -> "BanquetLeadStageChangeRequest":
        if self.target_stage == LeadStage.INVALID and not self.invalidation_reason:
            raise ValueError("target_stage=invalid 时 invalidation_reason 必填")
        return self
