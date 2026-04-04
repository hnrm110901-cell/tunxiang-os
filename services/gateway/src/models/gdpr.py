"""GDPR / 个人信息保护合规 — Pydantic 模型定义"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DataRequestType(str, enum.Enum):
    """数据主体请求类型（GDPR Article 15-17, 16）"""
    ACCESS = "access"
    EXPORT = "export"
    DELETE = "delete"
    RECTIFY = "rectify"


class DataRequestStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


# ── Request schemas ──────────────────────────────────────────────


class CreateDataRequestIn(BaseModel):
    customer_id: UUID
    request_type: DataRequestType
    reason: str | None = None


class AnonymizeCustomerIn(BaseModel):
    reason: str = "customer_request"


class RecordConsentIn(BaseModel):
    customer_id: UUID
    consent_type: str = Field(
        ...,
        description="同意类型，如 marketing / analytics / third_party",
    )
    granted: bool
    source: str = Field(
        default="web",
        description="同意来源：web / miniapp / pos / phone",
    )


# ── Response schemas ─────────────────────────────────────────────


class DataRequestOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    request_type: DataRequestType
    status: DataRequestStatus
    result_url: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AuditLogEntry(BaseModel):
    id: UUID
    tenant_id: UUID
    operator_id: str
    action: str
    target_customer_id: UUID | None = None
    detail: dict | None = None
    created_at: datetime


class ConsentRecord(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    consent_type: str
    granted: bool
    source: str
    created_at: datetime
