"""销售目标与进度契约 — 年/月/周/日 × 6 指标（R1 新增）

对应迁移：v266_sales_targets
对应事件：shared.events.event_types.SalesTargetEventType

周期类型（对标食尚订 §6 目标管理）：
  year / month / week / day

指标类型：
  revenue_fen         — 销售额（分）
  order_count         — 订单数
  table_count         — 桌数
  unit_avg_fen        — 单均（分）
  per_guest_avg_fen   — 人均（分）
  new_customer_count  — 新客数

金额字段统一带 _fen 后缀，单位为分（整数），对齐 CLAUDE.md §15。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PeriodType(str, Enum):
    """销售目标周期类型。"""

    YEAR = "year"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"


class MetricType(str, Enum):
    """销售目标指标类型。"""

    REVENUE_FEN = "revenue_fen"
    ORDER_COUNT = "order_count"
    TABLE_COUNT = "table_count"
    UNIT_AVG_FEN = "unit_avg_fen"
    PER_GUEST_AVG_FEN = "per_guest_avg_fen"
    NEW_CUSTOMER_COUNT = "new_customer_count"


class SalesTarget(BaseModel):
    """sales_targets 表单行契约。"""

    model_config = ConfigDict(from_attributes=True)

    target_id: UUID = Field(..., description="目标唯一ID")
    tenant_id: UUID = Field(..., description="租户ID，RLS 强制隔离")
    store_id: UUID | None = Field(
        default=None,
        description="门店ID（集团级目标可为空）",
    )
    employee_id: UUID = Field(..., description="目标归属员工（销售经理）")
    period_type: PeriodType = Field(..., description="周期类型")
    period_start: date = Field(..., description="周期起点（含）")
    period_end: date = Field(..., description="周期终点（含）")
    metric_type: MetricType = Field(..., description="指标类型")
    target_value: int = Field(
        ...,
        ge=0,
        description=(
            "目标值；金额类（_fen 后缀）单位为分（整数），"
            "其他为计数值（同样是整数）"
        ),
    )
    parent_target_id: UUID | None = Field(
        default=None,
        description="上级目标ID（年→月→周→日 分解链，可选）",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="目标说明（可选）",
    )
    created_by: UUID | None = Field(
        default=None,
        description="创建人员工ID",
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")

    @model_validator(mode="after")
    def _validate_period(self) -> "SalesTarget":
        if self.period_end < self.period_start:
            raise ValueError("period_end 必须 >= period_start")
        return self


class SalesProgress(BaseModel):
    """sales_progress 表单行契约（进度快照）。"""

    model_config = ConfigDict(from_attributes=True)

    progress_id: UUID = Field(..., description="进度记录唯一ID")
    tenant_id: UUID = Field(..., description="租户ID")
    target_id: UUID = Field(
        ...,
        description="关联 sales_targets.target_id",
    )
    actual_value: int = Field(
        ...,
        ge=0,
        description="实际完成值（金额类单位为分，其他为计数）",
    )
    achievement_rate: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("9.9999"),
        description="达成率（0.0000~9.9999，允许超 100%）",
    )
    snapshot_at: datetime = Field(
        ...,
        description="快照时间",
    )
    source_event_id: UUID | None = Field(
        default=None,
        description="触发本次快照的事件ID（可选）",
    )
    created_at: datetime = Field(..., description="创建时间")


class SalesTargetCreateRequest(BaseModel):
    """创建销售目标的输入契约。"""

    tenant_id: UUID = Field(..., description="租户ID")
    store_id: UUID | None = Field(
        default=None,
        description="门店ID",
    )
    employee_id: UUID = Field(..., description="目标归属员工")
    period_type: PeriodType = Field(..., description="周期类型")
    period_start: date = Field(..., description="周期起点")
    period_end: date = Field(..., description="周期终点")
    metric_type: MetricType = Field(..., description="指标类型")
    target_value: int = Field(..., ge=0, description="目标值")
    parent_target_id: UUID | None = Field(
        default=None,
        description="上级目标ID（可选）",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="备注",
    )

    @model_validator(mode="after")
    def _validate_period(self) -> "SalesTargetCreateRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end 必须 >= period_start")
        return self
