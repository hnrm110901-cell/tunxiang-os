"""价格台账 ORM 模型 + Pydantic V2 Schema（v366）

ORM 表（对应迁移 v366）：
  SupplierPriceHistoryORM — 价格快照台账
  PriceAlertRuleORM       — 预警阈值规则
  PriceAlertORM           — 触发的预警实例

Pydantic Schema：
  PriceRecordIn / PriceRecordOut
  PriceTrendPoint / PriceTrendOut
  SupplierComparePoint / SupplierCompareOut
  AlertRuleIn / AlertRuleOut
  PriceAlertOut / AlertAckIn

约定：
  - 所有金额单位为"分"（int）
  - 所有 UUID 字段使用 str 在 API 边界，UUID 在 ORM 边界
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ──────────────────────────────────────────────────────────────────────
# 常量 / 枚举
# ──────────────────────────────────────────────────────────────────────

ALERT_RULE_TYPES: tuple[str, ...] = (
    "ABSOLUTE_HIGH",  # 当前单价 >= 阈值（分）
    "ABSOLUTE_LOW",   # 当前单价 <= 阈值（分）
    "PERCENT_RISE",   # 相对基准窗口均价的涨幅 >= 阈值（百分点）
    "PERCENT_FALL",   # 跌幅 >= 阈值
    "YOY_RISE",       # 同比上一年同窗口的涨幅 >= 阈值
    "YOY_FALL",       # 同比下跌幅
)

ALERT_SEVERITIES: tuple[str, ...] = ("INFO", "WARNING", "CRITICAL")
ALERT_STATUSES: tuple[str, ...] = ("ACTIVE", "ACKED", "IGNORED")

SOURCE_DOC_TYPES: tuple[str, ...] = ("purchase_order", "receiving", "manual")


# ──────────────────────────────────────────────────────────────────────
# ORM 模型
# ──────────────────────────────────────────────────────────────────────


class SupplierPriceHistoryORM(TenantBase):
    """价格快照台账 — 每次收货/采购单/手工录入都写入一行"""

    __tablename__ = "supplier_price_history"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    unit_price_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_doc_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    source_doc_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )


class PriceAlertRuleORM(TenantBase):
    """预警阈值规则 — 一条规则可绑定全食材或单一食材"""

    __tablename__ = "price_alert_rules"

    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    baseline_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )


class PriceAlertORM(TenantBase):
    """触发的预警实例"""

    __tablename__ = "price_alerts"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("price_alert_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_price_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    baseline_price_fen: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    breach_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="WARNING"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE"
    )
    acked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    acked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ──────────────────────────────────────────────────────────────────────
# Pydantic V2 Schema
# ──────────────────────────────────────────────────────────────────────


class PriceRecordIn(BaseModel):
    """价格快照写入请求"""

    model_config = ConfigDict(extra="forbid")

    ingredient_id: str
    supplier_id: str
    unit_price_fen: int = Field(ge=0, description="单价（分），整数")
    quantity_unit: Optional[str] = Field(default=None, max_length=16)
    captured_at: Optional[datetime] = None
    source_doc_type: Optional[str] = Field(default="manual", max_length=32)
    source_doc_id: Optional[str] = None
    source_doc_no: Optional[str] = Field(default=None, max_length=64)
    store_id: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None

    @field_validator("source_doc_type")
    @classmethod
    def _check_source_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in SOURCE_DOC_TYPES:
            raise ValueError(f"source_doc_type 必须是 {SOURCE_DOC_TYPES} 之一")
        return v


class PriceRecordOut(BaseModel):
    id: str
    ingredient_id: str
    supplier_id: str
    unit_price_fen: int
    quantity_unit: Optional[str]
    captured_at: datetime
    source_doc_type: Optional[str]
    source_doc_id: Optional[str]
    source_doc_no: Optional[str]
    store_id: Optional[str]
    notes: Optional[str]


class PriceTrendPoint(BaseModel):
    """趋势聚合单点（按周/月）"""

    period_start: date
    avg_price_fen: int
    min_price_fen: int
    max_price_fen: int
    sample_count: int


class PriceTrendOut(BaseModel):
    ingredient_id: str
    bucket: str  # week|month
    points: list[PriceTrendPoint]


class SupplierComparePoint(BaseModel):
    """多供应商对比单点"""

    supplier_id: str
    avg_price_fen: int
    min_price_fen: int
    max_price_fen: int
    last_price_fen: int
    last_captured_at: datetime
    sample_count: int


class SupplierCompareOut(BaseModel):
    ingredient_id: str
    suppliers: list[SupplierComparePoint]


class AlertRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: Optional[str] = Field(
        default=None, description="NULL 表示该规则适用于全部食材"
    )
    rule_type: str
    threshold_value: Decimal
    baseline_window_days: int = Field(default=30, ge=1, le=365)
    enabled: bool = True
    created_by: Optional[str] = None

    @field_validator("rule_type")
    @classmethod
    def _check_rule_type(cls, v: str) -> str:
        if v not in ALERT_RULE_TYPES:
            raise ValueError(f"rule_type 必须是 {ALERT_RULE_TYPES} 之一")
        return v


class AlertRuleOut(BaseModel):
    id: str
    ingredient_id: Optional[str]
    rule_type: str
    threshold_value: Decimal
    baseline_window_days: int
    enabled: bool
    created_at: datetime


class PriceAlertOut(BaseModel):
    id: str
    rule_id: str
    ingredient_id: str
    supplier_id: Optional[str]
    triggered_at: datetime
    current_price_fen: int
    baseline_price_fen: Optional[int]
    breach_value: Optional[Decimal]
    severity: str
    status: str
    acked_by: Optional[str]
    acked_at: Optional[datetime]
    ack_comment: Optional[str]


class AlertAckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acked_by: str
    ack_comment: Optional[str] = None
    new_status: str = "ACKED"  # ACKED | IGNORED

    @field_validator("new_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in ("ACKED", "IGNORED"):
            raise ValueError("new_status 必须是 ACKED 或 IGNORED")
        return v
