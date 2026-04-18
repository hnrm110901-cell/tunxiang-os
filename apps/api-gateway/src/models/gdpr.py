"""
GDPR 合规数据模型

- DataConsentRecord：用户同意记录
- DataAccessRequest：数据主体访问请求（SAR：access/export/delete/correct）
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class DataConsentRecord(Base, TimestampMixin):
    """数据处理同意记录 — GDPR Art.6 合法性基础"""

    __tablename__ = "data_consent_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    # data_processing / marketing / third_party_share / ai_training
    consent_type = Column(String(40), nullable=False, index=True)
    granted = Column(Boolean, default=False, nullable=False)
    granted_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    # consent / contract / legal_obligation / vital_interests / public_task / legitimate_interests
    legal_basis = Column(String(40), nullable=False, default="consent")
    notes = Column(Text, nullable=True)


class DataAccessRequest(Base, TimestampMixin):
    """数据主体访问请求（SAR） — GDPR Art.15~22"""

    __tablename__ = "data_access_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    request_type = Column(String(20), nullable=False)  # access / export / delete / correct
    status = Column(String(20), default="pending", nullable=False)  # pending / processing / completed / rejected
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    export_file_url = Column(String(500), nullable=True)
    rejection_reason = Column(Text, nullable=True)
