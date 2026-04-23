"""客户生命周期状态机契约 — 四象限 FSM（R1 新增）

对应迁移：v264_customer_lifecycle_fsm
对应事件：shared.events.event_types.CustomerLifecycleEventType

四象限定义：
  no_order  — 从未下单的新注册客户
  active    — 近 N 天有消费（N 由门店配置，默认 90 天）
  dormant   — 超过 N 天无消费但未达流失阈值
  churned   — 超过 M 天无消费（M > N，默认 180 天）

状态流转：
  no_order ──首单──> active
  active ──超时──> dormant ──超时──> churned
  dormant / churned ──消费──> active（唤醒/召回）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomerLifecycleState(str, Enum):
    """客户生命周期四象限状态。"""

    NO_ORDER = "no_order"
    ACTIVE = "active"
    DORMANT = "dormant"
    CHURNED = "churned"


class CustomerLifecycleRecord(BaseModel):
    """customer_lifecycle_state 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID = Field(..., description="客户唯一ID（Golden Customer）")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    state: CustomerLifecycleState = Field(
        ...,
        description="当前生命周期状态（四象限之一）",
    )
    since_ts: datetime = Field(
        ...,
        description="进入当前状态的起点时间（用于计算驻留时长）",
    )
    previous_state: CustomerLifecycleState | None = Field(
        default=None,
        description="上一状态（NULL 表示首次写入）",
    )
    transition_count: int = Field(
        default=0,
        ge=0,
        description="状态跃迁累计次数",
    )
    last_transition_event_id: UUID | None = Field(
        default=None,
        description="最近一次状态变更的事件ID，指向 events 表",
    )
    updated_at: datetime = Field(
        ...,
        description="记录最后更新时间",
    )


class CustomerLifecycleTransitionRequest(BaseModel):
    """状态迁移输入契约（Projector / Agent 写入用）。"""

    customer_id: UUID = Field(..., description="目标客户ID")
    tenant_id: UUID = Field(..., description="租户ID")
    target_state: CustomerLifecycleState = Field(
        ...,
        description="目标状态",
    )
    source_event_id: UUID = Field(
        ...,
        description="触发本次迁移的事件ID（写入 events 表的 stream_id）",
    )
    occurred_at: datetime = Field(
        ...,
        description="业务时间，与 events.occurred_at 对齐",
    )
    reason: str | None = Field(
        default=None,
        max_length=200,
        description="迁移原因（可选，用于决策留痕）",
    )
