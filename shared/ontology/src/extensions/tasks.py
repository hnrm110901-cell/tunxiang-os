"""任务引擎契约 — 10 类销售/服务任务（R1 新增）

对应迁移：v265_tasks
对应事件：shared.events.event_types.TaskEventType

10 类任务来源（对标食尚订 §4-§6 + 路线图 §4 L4）：
  lead_follow_up    — 商机跟进
  banquet_stage     — 宴会 6 阶段节点
  dining_followup   — 餐后 D+1 回访
  birthday          — 生日前 7 天
  anniversary       — 纪念日
  dormant_recall    — 沉睡唤醒
  new_customer      — 新客 48h 回访
  confirm_arrival   — 核餐 T-2h
  adhoc             — 临时任务
  banquet_followup  — 宴会餐后回访

升级规则：
  销售未跟 → 店长 → 区经（由 sales_coach Agent 触发）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskType(str, Enum):
    """10 类任务类型。"""

    LEAD_FOLLOW_UP = "lead_follow_up"
    BANQUET_STAGE = "banquet_stage"
    DINING_FOLLOWUP = "dining_followup"
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    DORMANT_RECALL = "dormant_recall"
    NEW_CUSTOMER = "new_customer"
    CONFIRM_ARRIVAL = "confirm_arrival"
    ADHOC = "adhoc"
    BANQUET_FOLLOWUP = "banquet_followup"


class TaskStatus(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """tasks 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID = Field(..., description="任务唯一ID")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    store_id: UUID | None = Field(
        default=None,
        description="门店ID，集团任务可为空",
    )
    task_type: TaskType = Field(..., description="10 类任务类型之一")
    assignee_employee_id: UUID = Field(
        ...,
        description="派单对象员工ID",
    )
    customer_id: UUID | None = Field(
        default=None,
        description="目标客户ID（如适用）",
    )
    due_at: datetime = Field(
        ...,
        description="任务截止时间（逾期触发升级）",
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="任务当前状态",
    )
    escalated_to_employee_id: UUID | None = Field(
        default=None,
        description="升级对象员工ID（升级后写入）",
    )
    escalated_at: datetime | None = Field(
        default=None,
        description="升级发生时间",
    )
    cancel_reason: str | None = Field(
        default=None,
        max_length=200,
        description="取消原因（status=cancelled 时必填）",
    )
    source_event_id: UUID | None = Field(
        default=None,
        description="触发该任务的事件ID（因果链）",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "任务上下文，典型结构："
            "{reservation_id, banquet_lead_id, target_id, channel, notes}"
        ),
    )
    dispatched_at: datetime = Field(
        ...,
        description="派发时间",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="完成时间（status=completed 时写入）",
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class TaskDispatchRequest(BaseModel):
    """任务派发请求契约（sales_coach Agent / 手动派单 API 共用）。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(
        default=None,
        description="门店ID（集团任务可为空）",
    )
    task_type: TaskType = Field(..., description="任务类型")
    assignee_employee_id: UUID = Field(
        ...,
        description="派单对象",
    )
    customer_id: UUID | None = Field(
        default=None,
        description="目标客户ID",
    )
    due_at: datetime = Field(
        ...,
        description="截止时间",
    )
    source_event_id: UUID | None = Field(
        default=None,
        description="触发事件ID（可选）",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="任务上下文 JSON",
    )


class TaskDispatchResponse(BaseModel):
    """任务派发响应契约。"""

    ok: bool = Field(..., description="是否派发成功")
    task_id: UUID = Field(..., description="新建任务ID")
    dispatched_at: datetime = Field(..., description="派发时间戳")
    event_id: UUID | None = Field(
        default=None,
        description="写入事件总线的 task.dispatched 事件ID",
    )
