"""配送签收凭证 ORM 模型 + Pydantic Schema（TASK-4，v369）

表：
  delivery_receipts          — 电子签收单（一个配送单只能签一次）
  delivery_damage_records    — 配送损坏记录（多条）
  delivery_attachments       — 附件（照片/视频，关联 RECEIPT 或 DAMAGE）

枚举：
  SignerRole          — STORE_MANAGER / RECEIVER / OTHER
  DamageType          — BROKEN / SPOILED / WRONG_SPEC / WRONG_QTY / EXPIRED / OTHER
  Severity            — MINOR / MAJOR / CRITICAL
  ResolutionStatus    — PENDING / RETURNED / COMPENSATED / ACCEPTED
  EntityType          — RECEIPT / DAMAGE
  DamageResolveAction — 处理动作（红字凭证 / 替换发货 / 内部消化）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ──────────────────────────────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────────────────────────────


class SignerRole(str, Enum):
    STORE_MANAGER = "STORE_MANAGER"
    RECEIVER = "RECEIVER"
    OTHER = "OTHER"


class DamageType(str, Enum):
    BROKEN = "BROKEN"          # 包装/产品破损
    SPOILED = "SPOILED"        # 变质腐败
    WRONG_SPEC = "WRONG_SPEC"  # 规格错误
    WRONG_QTY = "WRONG_QTY"    # 数量短少
    EXPIRED = "EXPIRED"        # 临期/过期
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ResolutionStatus(str, Enum):
    PENDING = "PENDING"
    RETURNED = "RETURNED"          # 整批退回供应商（触发红字凭证事件）
    COMPENSATED = "COMPENSATED"    # 供应商赔偿/补货
    ACCEPTED = "ACCEPTED"          # 门店接受（自行消化）


class EntityType(str, Enum):
    RECEIPT = "RECEIPT"
    DAMAGE = "DAMAGE"


class DamageResolveAction(str, Enum):
    """损坏处理动作（resolve_action 字段建议值）"""
    RETURN_TO_SUPPLIER = "RETURN_TO_SUPPLIER"
    REQUEST_COMPENSATION = "REQUEST_COMPENSATION"
    REQUEST_REPLACEMENT = "REQUEST_REPLACEMENT"
    ACCEPT_AS_IS = "ACCEPT_AS_IS"


# ──────────────────────────────────────────────────────────────────────
# ORM 模型
# ──────────────────────────────────────────────────────────────────────


class DeliveryReceipt(TenantBase):
    """电子签收单 — 一个 delivery_id 对应一份"""

    __tablename__ = "delivery_receipts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "delivery_id",
            name="uq_delivery_receipts_tenant_delivery",
        ),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    signer_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    signer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    signature_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    signature_location_lat: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 7), nullable=True,
    )
    signature_location_lng: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 7), nullable=True,
    )
    device_info: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DeliveryDamageRecord(TenantBase):
    """配送损坏记录"""

    __tablename__ = "delivery_damage_records"

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    batch_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    damage_type: Mapped[str] = mapped_column(String(24), nullable=False)
    damaged_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost_fen: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    damage_amount_fen: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        Computed(
            "CASE WHEN unit_cost_fen IS NULL THEN NULL "
            "ELSE (damaged_qty * unit_cost_fen)::BIGINT END",
            persisted=True,
        ),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="MINOR",
    )
    reported_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    resolution_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="PENDING",
    )
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolve_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resolve_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DeliveryAttachment(TenantBase):
    """附件（照片/视频）— 关联签收单或损坏记录"""

    __tablename__ = "delivery_attachments"

    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    captured_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    gps_lat: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    gps_lng: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


# ──────────────────────────────────────────────────────────────────────
# Pydantic Schema（API 入参/出参）
# ──────────────────────────────────────────────────────────────────────


class DeviceInfo(BaseModel):
    model: Optional[str] = None
    os: Optional[str] = None
    app_version: Optional[str] = None


class SignatureSubmitIn(BaseModel):
    """POST /sign 入参"""
    model_config = ConfigDict(use_enum_values=True)

    signer_name: str = Field(min_length=1, max_length=64)
    signer_role: Optional[SignerRole] = None
    signer_phone: Optional[str] = Field(default=None, max_length=32)
    signature_base64: str = Field(
        ...,
        description="data:image/png;base64,xxx 或 data:image/jpeg;base64,xxx",
    )
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    device_info: Optional[DeviceInfo] = None
    notes: Optional[str] = None


class DamageRecordIn(BaseModel):
    """POST /damage 入参"""
    model_config = ConfigDict(use_enum_values=True)

    item_id: Optional[uuid.UUID] = None
    ingredient_id: Optional[uuid.UUID] = None
    batch_no: Optional[str] = Field(default=None, max_length=64)
    damage_type: DamageType
    damaged_qty: Decimal = Field(gt=Decimal("0"))
    unit_cost_fen: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = None
    severity: Severity = Severity.MINOR
    reported_by: Optional[uuid.UUID] = None


class AttachmentIn(BaseModel):
    """POST /damage/{id}/attachment 入参"""
    model_config = ConfigDict(use_enum_values=True)

    entity_type: EntityType
    file_base64: str = Field(
        ...,
        description="data:image/jpeg;base64,xxx 或 data:video/mp4;base64,xxx",
    )
    file_name: Optional[str] = Field(default=None, max_length=255)
    captured_at: Optional[datetime] = None
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    uploaded_by: Optional[uuid.UUID] = None


class ResolveDamageIn(BaseModel):
    """POST /damage/{id}/resolve 入参"""
    model_config = ConfigDict(use_enum_values=True)

    action: ResolutionStatus = Field(
        ...,
        description="RETURNED|COMPENSATED|ACCEPTED（PENDING 不可作为目标态）",
    )
    resolve_action_code: Optional[DamageResolveAction] = None
    comment: Optional[str] = None
    resolved_by: Optional[uuid.UUID] = None
