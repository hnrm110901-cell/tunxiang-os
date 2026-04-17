"""
D10 换班审批流模型 — Should-Fix P1
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class ShiftSwapStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ShiftSwapRequest(Base, TimestampMixin):
    """换班申请"""

    __tablename__ = "shift_swap_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    requester_id = Column(String(50), nullable=False, index=True)        # 申请人
    target_employee_id = Column(String(50), nullable=False, index=True)  # 目标换班员工

    original_shift_id = Column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False, index=True
    )
    swap_shift_id = Column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False, index=True
    )

    reason = Column(Text, nullable=True)
    status = Column(String(20), default=ShiftSwapStatus.PENDING.value, nullable=False, index=True)

    approver_id = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<ShiftSwapRequest(req={self.requester_id}, "
            f"target={self.target_employee_id}, status={self.status})>"
        )
