"""供应商配送时间窗 ORM + Pydantic Schema（PRD-05 / Tier 1 食安）

ORM（SQLAlchemy 2.0）：
  SupplierDeliveryWindow      — 时间窗配置（含 weekday_mask + 二级审批 + grace 容忍度）
  SupplierDeliveryViolation   — 违约日志（append-only；supplier_scoring 聚合扣分基础）

Pydantic V2 Schema：
  DeliveryWindow Create / Update / Read 模型 + Approve 请求体 + CheckRequest/Response
  DeliveryViolation Read 模型

枚举：
  ViolationKind — late / early
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────────────────────────────────────
# 枚举（与 CHECK 约束对齐）
# ─────────────────────────────────────────────────────────────────────────────


class ViolationKind(str, Enum):
    """违约类型 — 晚到 / 早到（早到亦影响后厨节奏）"""

    LATE = "late"
    EARLY = "early"


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class SupplierDeliveryWindow(TenantBase):
    """供应商配送时间窗配置（supplier_delivery_windows）

    weekday_mask 约定：bit 0 = 周一 ... bit 6 = 周日；7 位齐全 = 127
    """

    __tablename__ = "supplier_delivery_windows"

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=127)
    earliest_time: Mapped[time] = mapped_column(Time, nullable=False)
    latest_time: Mapped[time] = mapped_column(Time, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    auto_reject_on_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class SupplierDeliveryViolation(TenantBase):
    """供应商配送违约日志（append-only — 每收货单至多一条）"""

    __tablename__ = "supplier_delivery_violations"

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    receiving_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    window_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    scheduled_earliest: Mapped[time] = mapped_column(Time, nullable=False)
    scheduled_latest: Mapped[time] = mapped_column(Time, nullable=False)
    actual_signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    violation_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    violation_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class DeliveryWindowCreate(_BaseSchema):
    """创建配送时间窗（草稿态 — approved_by 为 NULL）"""

    supplier_id: str
    store_id: str
    earliest_time: time = Field(..., description="例如 04:00:00 = 4 点最早")
    latest_time: time = Field(..., description="例如 07:00:00 = 7 点最晚")
    weekday_mask: int = Field(default=127, ge=1, le=127, description="1-127 bitmask")
    grace_minutes: int = Field(default=15, ge=0, le=240)
    auto_reject_on_late: bool = False
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_time_order(self) -> "DeliveryWindowCreate":
        if self.earliest_time >= self.latest_time:
            raise ValueError("earliest_time 必须早于 latest_time")
        return self


class DeliveryWindowUpdate(_BaseSchema):
    """更新配送时间窗（仅草稿态可改 — 与 weight/yield 同 pattern，本 PR P0 仅创建/审批/软删）"""

    earliest_time: Optional[time] = None
    latest_time: Optional[time] = None
    weekday_mask: Optional[int] = Field(default=None, ge=1, le=127)
    grace_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    auto_reject_on_late: Optional[bool] = None
    notes: Optional[str] = None


class DeliveryWindowRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    store_id: uuid.UUID
    weekday_mask: int
    earliest_time: time
    latest_time: time
    grace_minutes: int
    auto_reject_on_late: bool
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ApproveRequest(_BaseSchema):
    """二级审批请求"""

    approver_id: str = Field(..., description="审批人 ID（必须 != created_by）")


class CheckWindowRequest(_BaseSchema):
    """收货签收前 / 完成路径：检查时间窗合规性"""

    supplier_id: str
    store_id: str
    signed_at: datetime = Field(..., description="实际签收时刻（store-local 解读）")


class CheckWindowResponse(_BaseSchema):
    within_window: bool
    window_id: Optional[str]
    weekday_matched: bool
    scheduled_earliest: Optional[time]
    scheduled_latest: Optional[time]
    grace_minutes: Optional[int]
    violation_minutes: int = 0
    violation_kind: Optional[str] = None


class DeliveryViolationRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    store_id: uuid.UUID
    receiving_order_id: uuid.UUID
    window_id: Optional[uuid.UUID]
    scheduled_earliest: time
    scheduled_latest: time
    actual_signed_at: datetime
    violation_minutes: int
    violation_kind: str
    recorded_at: datetime
