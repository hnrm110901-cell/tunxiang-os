"""宴会主订单与状态日志 ORM模型 — Phase 1"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class Banquet(TenantBase):
    """宴会主订单"""

    __tablename__ = "banquets"

    banquet_no: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
        comment="业务ID BQT-XXXXXXXXXXXX",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    venue_booking_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # --- 客户信息 ---
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    time_slot: Mapped[str] = mapped_column(
        String(20),
        default="lunch",
        comment="lunch/dinner/full_day",
    )

    # --- 规模 ---
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    venue_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # --- 金额(分) ---
    subtotal_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="菜品小计(分)",
    )
    service_charge_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="服务费(分)",
    )
    venue_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="场地费(分)",
    )
    decoration_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="布置费(分)",
    )
    other_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="其他费用(分)",
    )
    discount_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="优惠减免(分)",
    )
    total_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="订单总价(分)",
    )
    deposit_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.3000"),
    )
    deposit_required_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="应收定金(分)",
    )
    deposit_paid_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="已收定金(分)",
    )
    final_paid_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="尾款已付(分)",
    )
    refund_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="退款金额(分)",
    )

    # --- 状态 ---
    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        index=True,
        comment="draft/confirmed/preparing/ready/in_progress/completed/cancelled/settled",
    )
    deposit_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fully_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- 执行信息 ---
    assigned_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="宴会负责人",
    )
    menu_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="菜单已确认",
    )
    menu_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开席时间",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间",
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="结算时间",
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # --- 扩展 ---
    special_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contract_terms: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="合同条款快照",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_bqt_store", "tenant_id", "store_id"),
        Index("idx_bqt_status", "tenant_id", "status"),
        Index("idx_bqt_event_date", "tenant_id", "event_date"),
        Index("idx_bqt_lead", "tenant_id", "lead_id"),
        {"comment": "宴会主订单"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "banquet_no": self.banquet_no,
            "store_id": str(self.store_id),
            "lead_id": str(self.lead_id) if self.lead_id else None,
            "quote_id": str(self.quote_id) if self.quote_id else None,
            "venue_booking_id": str(self.venue_booking_id) if self.venue_booking_id else None,
            "customer_name": self.customer_name,
            "phone": self.phone,
            "company": self.company,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "time_slot": self.time_slot,
            "table_count": self.table_count,
            "guest_count": self.guest_count,
            "venue_id": str(self.venue_id) if self.venue_id else None,
            "subtotal_fen": self.subtotal_fen,
            "service_charge_fen": self.service_charge_fen,
            "venue_fee_fen": self.venue_fee_fen,
            "decoration_fee_fen": self.decoration_fee_fen,
            "other_fee_fen": self.other_fee_fen,
            "discount_fen": self.discount_fen,
            "total_fen": self.total_fen,
            "deposit_rate": float(self.deposit_rate) if self.deposit_rate else None,
            "deposit_required_fen": self.deposit_required_fen,
            "deposit_paid_fen": self.deposit_paid_fen,
            "final_paid_fen": self.final_paid_fen,
            "refund_fen": self.refund_fen,
            "status": self.status,
            "deposit_paid": self.deposit_paid,
            "is_fully_paid": self.is_fully_paid,
            "assigned_manager_id": str(self.assigned_manager_id) if self.assigned_manager_id else None,
            "menu_confirmed": self.menu_confirmed,
            "menu_confirmed_at": self.menu_confirmed_at.isoformat() if self.menu_confirmed_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "special_requirements": self.special_requirements,
            "contract_terms": self.contract_terms,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetStatusLog(TenantBase):
    """宴会状态变更日志"""

    __tablename__ = "banquet_status_logs"

    banquet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    extra: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="状态变更附加数据",
    )

    __table_args__ = (
        Index("idx_bsl_banquet", "tenant_id", "banquet_id"),
        {"comment": "宴会状态变更日志"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "banquet_id": str(self.banquet_id),
            "from_status": self.from_status,
            "to_status": self.to_status,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "reason": self.reason,
            "extra": self.extra,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }
