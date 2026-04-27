"""配送在途温控 ORM 模型 + Pydantic Schema (TASK-3 / v368)

表：
  delivery_temperature_thresholds  阈值配置（GLOBAL/TEMPERATURE_TYPE/CATEGORY/SKU 优先级）
  delivery_temperature_logs        时序温度数据（按 recorded_at 月分区 + brin 索引）
  delivery_temperature_alerts      超限告警实例（合并连续超限）

外部使用：
  from services.tx_supply.src.models.delivery_temperature import (
      DeliveryTemperatureThreshold,
      DeliveryTemperatureLog,
      DeliveryTemperatureAlert,
      BreachType, Severity, AlertStatus, ScopeType, Source,
  )
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─── 枚举 ──────────────────────────────────────────────────────────────


class ScopeType(str, Enum):
    GLOBAL = "GLOBAL"
    TEMPERATURE_TYPE = "TEMPERATURE_TYPE"  # 例如 REFRIGERATED / FROZEN / HOT
    CATEGORY = "CATEGORY"  # 例如 seafood / meat / vegetable
    SKU = "SKU"


class BreachType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HANDLED = "HANDLED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class Source(str, Enum):
    DEVICE = "DEVICE"  # IoT 温度计
    MOBILE = "MOBILE"  # 司机手机扫码上报
    MANUAL = "MANUAL"  # 后台人工补录


# 优先级越高越先匹配（SKU > CATEGORY > TEMPERATURE_TYPE > GLOBAL）
SCOPE_PRIORITY: dict[str, int] = {
    ScopeType.SKU.value: 4,
    ScopeType.CATEGORY.value: 3,
    ScopeType.TEMPERATURE_TYPE.value: 2,
    ScopeType.GLOBAL.value: 1,
}


# ─── ORM 模型 ──────────────────────────────────────────────────────────


class DeliveryTemperatureThreshold(TenantBase):
    """阈值配置（按优先级匹配）"""

    __tablename__ = "delivery_temperature_thresholds"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('GLOBAL','TEMPERATURE_TYPE','CATEGORY','SKU')",
            name="ck_delivery_temp_thresholds_scope_type_orm",
        ),
    )

    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_temp_celsius: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_temp_celsius: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    alert_min_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeliveryTemperatureLog(TenantBase):
    """时序温度记录（分区表，主键 (id, recorded_at)）"""

    __tablename__ = "delivery_temperature_logs"

    # 注意：分区表的主键必须包含 recorded_at；TenantBase 已提供 id PK，
    # 这里复用 id 字段，DDL 在迁移中已声明为 (id, recorded_at) 复合主键。

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    temperature_celsius: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    humidity_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    gps_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    gps_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=Source.DEVICE.value)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DeliveryTemperatureAlert(TenantBase):
    """超限告警实例（连续超限合并为一条）"""

    __tablename__ = "delivery_temperature_alerts"

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    threshold_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("delivery_temperature_thresholds.id"),
        nullable=True,
    )
    breach_type: Mapped[str] = mapped_column(String(8), nullable=False)
    breach_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    breach_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_temperature_celsius: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    threshold_min_celsius: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    threshold_max_celsius: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.WARNING.value)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertStatus.ACTIVE.value)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handle_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    handle_action: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ─── Pydantic Schemas (V2) ────────────────────────────────────────────


class ThresholdCreate(BaseModel):
    scope_type: ScopeType
    scope_value: Optional[str] = None
    min_temp_celsius: Optional[float] = None
    max_temp_celsius: Optional[float] = None
    alert_min_seconds: int = Field(default=60, ge=1, le=3600)
    enabled: bool = True
    description: Optional[str] = None

    @field_validator("max_temp_celsius")
    @classmethod
    def _check_range(cls, v: Optional[float], info: Any) -> Optional[float]:
        min_v = info.data.get("min_temp_celsius")
        if v is not None and min_v is not None and v < min_v:
            raise ValueError("max_temp_celsius 不能小于 min_temp_celsius")
        return v


class ThresholdRead(BaseModel):
    id: str
    scope_type: str
    scope_value: Optional[str]
    min_temp_celsius: Optional[float]
    max_temp_celsius: Optional[float]
    alert_min_seconds: int
    enabled: bool
    description: Optional[str] = None
    created_at: Optional[str] = None


class TemperatureRecord(BaseModel):
    """单条温度上报"""

    recorded_at: Optional[datetime] = None  # 默认 NOW()
    temperature_celsius: float
    humidity_percent: Optional[float] = None
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    device_id: Optional[str] = None
    source: Source = Source.DEVICE
    extra: Optional[dict] = None


class TemperatureBatchRecord(BaseModel):
    """批量上报"""

    records: list[TemperatureRecord] = Field(min_length=1, max_length=2000)


class AlertHandlePayload(BaseModel):
    action: str = Field(min_length=1, max_length=32, description="例如 ADJUSTED|FALSE_POSITIVE|REROUTE")
    comment: Optional[str] = None
    handled_by: Optional[str] = None


__all__ = [
    "ScopeType",
    "BreachType",
    "Severity",
    "AlertStatus",
    "Source",
    "SCOPE_PRIORITY",
    "DeliveryTemperatureThreshold",
    "DeliveryTemperatureLog",
    "DeliveryTemperatureAlert",
    "ThresholdCreate",
    "ThresholdRead",
    "TemperatureRecord",
    "TemperatureBatchRecord",
    "AlertHandlePayload",
]
