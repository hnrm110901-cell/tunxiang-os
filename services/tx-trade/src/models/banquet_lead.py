"""宴会线索与客资管理 ORM模型 — Phase 1"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetLead(TenantBase):
    """宴会线索"""

    __tablename__ = "banquet_leads"

    lead_no: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
        comment="业务ID BQL-XXXXXXXXXXXX",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    event_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="wedding/birthday/business/tour_group/conference/annual_party/memorial/other",
    )
    event_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    guest_count_est: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    table_count_est: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    budget_per_table_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="每桌预算(分)",
    )
    source_channel: Mapped[str] = mapped_column(
        String(30),
        default="walk_in",
        comment="walk_in/phone/wechat/meituan/douyin/referral/website/other",
    )
    assigned_sales_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="new",
        index=True,
        comment="new/following/quoted/contracted/won/lost",
    )
    priority: Mapped[str] = mapped_column(
        String(10),
        default="normal",
        comment="low/normal/high/urgent",
    )
    follow_up_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lost_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    referral_lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_bl_tenant_store", "tenant_id", "store_id"),
        Index("idx_bl_status", "tenant_id", "status"),
        Index("idx_bl_event_date", "tenant_id", "event_date"),
        {"comment": "宴会线索"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "lead_no": self.lead_no,
            "store_id": str(self.store_id),
            "customer_name": self.customer_name,
            "phone": self.phone,
            "company": self.company,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "guest_count_est": self.guest_count_est,
            "table_count_est": self.table_count_est,
            "budget_per_table_fen": self.budget_per_table_fen,
            "source_channel": self.source_channel,
            "assigned_sales_id": str(self.assigned_sales_id) if self.assigned_sales_id else None,
            "status": self.status,
            "priority": self.priority,
            "follow_up_at": self.follow_up_at.isoformat() if self.follow_up_at else None,
            "lost_reason": self.lost_reason,
            "referral_lead_id": str(self.referral_lead_id) if self.referral_lead_id else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetLeadFollowUp(TenantBase):
    """宴会线索跟进记录"""

    __tablename__ = "banquet_lead_follow_ups"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    sales_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    follow_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="call/wechat/visit/tasting/other",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    next_follow_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    result: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="interested/hesitant/rejected/scheduled_tasting/signed",
    )
    attachments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_blfu_lead", "tenant_id", "lead_id"),
        Index("idx_blfu_sales", "tenant_id", "sales_id"),
        {"comment": "宴会线索跟进记录"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "lead_id": str(self.lead_id),
            "sales_id": str(self.sales_id),
            "follow_type": self.follow_type,
            "content": self.content,
            "next_follow_at": self.next_follow_at.isoformat() if self.next_follow_at else None,
            "result": self.result,
            "attachments": self.attachments,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetLeadTransfer(TenantBase):
    """宴会线索转移记录"""

    __tablename__ = "banquet_lead_transfers"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    from_sales_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    to_sales_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        comment="pending/approved/rejected",
    )

    __table_args__ = (
        Index("idx_blt_lead", "tenant_id", "lead_id"),
        {"comment": "宴会线索转移记录"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "lead_id": str(self.lead_id),
            "from_sales_id": str(self.from_sales_id),
            "to_sales_id": str(self.to_sales_id),
            "reason": self.reason,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }
