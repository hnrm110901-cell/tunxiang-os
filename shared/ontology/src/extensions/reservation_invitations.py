"""预订礼宾员邀请函与核餐电话契约（R2 新增）

对应迁移：v281_invitation_and_confirm_call
对应事件：shared.events.event_types.R2ReservationEventType

通道（channel）：
  sms    — 短信（通常带券码）
  wechat — 微信（H5 邀请函 + 模板消息）
  call   — AI 外呼电话（核餐 T-2h 场景）

状态（status）生命周期：
  pending → sent → confirmed  （客户确认到店/接受邀请）
  pending → sent → failed     （发送成功但客户未响应 / 发送失败）

金额字段以 _fen 结尾，单位为分（整数）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvitationChannel(str, Enum):
    """邀请/外呼通道类型。"""

    SMS = "sms"
    WECHAT = "wechat"
    CALL = "call"


class InvitationStatus(str, Enum):
    """邀请/外呼状态机。"""

    PENDING = "pending"
    SENT = "sent"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class InvitationRecord(BaseModel):
    """reservation_invitations 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    invitation_id: UUID = Field(..., description="邀请记录唯一ID")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    store_id: UUID | None = Field(
        default=None,
        description="归属门店ID（集团批量邀请可为空）",
    )
    reservation_id: UUID = Field(
        ...,
        description="关联预订ID（指向现有 reservations 表）",
    )
    customer_id: UUID | None = Field(
        default=None,
        description="目标客户ID（Golden Customer，可空表示待识别）",
    )
    channel: InvitationChannel = Field(
        ...,
        description="发送通道：sms/wechat/call",
    )
    status: InvitationStatus = Field(
        default=InvitationStatus.PENDING,
        description="当前状态",
    )
    sent_at: datetime | None = Field(
        default=None,
        description="发送时间（status=sent/confirmed/failed 时必填）",
    )
    confirmed_at: datetime | None = Field(
        default=None,
        description="客户确认到店时间（status=confirmed 时必填）",
    )
    coupon_code: str | None = Field(
        default=None,
        max_length=64,
        description="附带券码（邀请函场景）",
    )
    coupon_value_fen: int = Field(
        default=0,
        ge=0,
        description="附带券面值（分/整数，对齐金额公约）",
    )
    failure_reason: str | None = Field(
        default=None,
        max_length=200,
        description="失败原因（status=failed 时必填）",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "通道附加上下文 JSON：短信模板 / 微信 template_id / "
            "外呼话术脚本ID / Whisper 识别结果等"
        ),
    )
    source_event_id: UUID | None = Field(
        default=None,
        description="触发本次邀请的事件ID（因果链）",
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

    @model_validator(mode="after")
    def _validate_status_fields(self) -> "InvitationRecord":
        if self.status == InvitationStatus.CONFIRMED and not self.confirmed_at:
            raise ValueError("status=confirmed 时 confirmed_at 必填")
        if self.status == InvitationStatus.FAILED and not self.failure_reason:
            raise ValueError("status=failed 时 failure_reason 必填")
        return self


class InvitationCreateRequest(BaseModel):
    """邀请函/外呼发送请求契约（send_invitation / confirm_arrival 共用）。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(default=None, description="门店ID")
    reservation_id: UUID = Field(..., description="预订ID")
    customer_id: UUID | None = Field(default=None, description="客户ID")
    channel: InvitationChannel = Field(..., description="发送通道")
    coupon_code: str | None = Field(
        default=None,
        max_length=64,
        description="附带券码（可选）",
    )
    coupon_value_fen: int = Field(
        default=0,
        ge=0,
        description="附带券面值（分）",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="通道附加上下文",
    )
    source_event_id: UUID | None = Field(
        default=None,
        description="触发事件ID（可选）",
    )


class InvitationUpdateRequest(BaseModel):
    """邀请状态更新请求契约（回调 / 状态跃迁时使用）。"""

    invitation_id: UUID = Field(..., description="邀请记录ID")
    tenant_id: UUID = Field(..., description="租户ID")
    target_status: InvitationStatus = Field(..., description="目标状态")
    sent_at: datetime | None = Field(
        default=None,
        description="发送时间（target_status=sent/confirmed/failed 时必填）",
    )
    confirmed_at: datetime | None = Field(
        default=None,
        description="确认时间（target_status=confirmed 时必填）",
    )
    failure_reason: str | None = Field(
        default=None,
        max_length=200,
        description="失败原因（target_status=failed 时必填）",
    )

    @model_validator(mode="after")
    def _validate_target_status(self) -> "InvitationUpdateRequest":
        if self.target_status == InvitationStatus.CONFIRMED and not self.confirmed_at:
            raise ValueError("target_status=confirmed 时 confirmed_at 必填")
        if self.target_status == InvitationStatus.FAILED and not self.failure_reason:
            raise ValueError("target_status=failed 时 failure_reason 必填")
        return self
