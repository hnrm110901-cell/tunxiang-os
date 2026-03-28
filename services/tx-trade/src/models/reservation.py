"""预订模型 — 7状态机，支持包间分配与定金"""
import uuid

from sqlalchemy import String, Integer, Boolean, Date, Index
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase
from .enums import ReservationStatus, ReservationType


class Reservation(TenantBase):
    """预订记录"""
    __tablename__ = "reservations"

    reservation_id: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True,
        comment="业务ID如RSV-XXXXXXXXXXXX",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    confirmation_code: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="6位确认码",
    )
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReservationType.regular.value,
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False, comment="YYYY-MM-DD")
    time: Mapped[str] = mapped_column(String(5), nullable=False, comment="HH:MM")
    estimated_end_time: Mapped[str | None] = mapped_column(String(5), comment="HH:MM")
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # 包间
    room_name: Mapped[str | None] = mapped_column(String(50))
    room_info: Mapped[dict | None] = mapped_column(JSON, comment="包间详情")

    # 桌台
    table_no: Mapped[str | None] = mapped_column(String(20))

    # 特殊需求
    special_requests: Mapped[str | None] = mapped_column(String(500))

    # 定金
    deposit_required: Mapped[bool] = mapped_column(Boolean, default=False)
    deposit_amount_fen: Mapped[int] = mapped_column(Integer, default=0, comment="定金(分)")
    deposit_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    # 关联
    consumer_id: Mapped[str | None] = mapped_column(String(50), comment="会员ID")
    queue_id: Mapped[str | None] = mapped_column(String(20), comment="关联排队ID")
    order_id: Mapped[str | None] = mapped_column(String(50), comment="关联订单ID")

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReservationStatus.pending.value, index=True,
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    cancel_fee_fen: Mapped[int] = mapped_column(Integer, default=0, comment="取消手续费(分)")
    no_show_recorded: Mapped[bool] = mapped_column(Boolean, default=False)

    # 时间线
    arrived_at: Mapped[str | None] = mapped_column(String(50))
    seated_at: Mapped[str | None] = mapped_column(String(50))
    completed_at: Mapped[str | None] = mapped_column(String(50))
    cancelled_at: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        Index("idx_reservation_store_date", "store_id", "date"),
        Index("idx_reservation_store_status", "store_id", "status"),
        {"comment": "预订记录"},
    )

    def to_dict(self) -> dict:
        """转为业务字典（保持与原内存结构兼容）"""
        return {
            "reservation_id": self.reservation_id,
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "confirmation_code": self.confirmation_code,
            "customer_name": self.customer_name,
            "phone": self.phone,
            "type": self.type,
            "date": self.date,
            "time": self.time,
            "estimated_end_time": self.estimated_end_time,
            "party_size": self.party_size,
            "room_name": self.room_name,
            "room_info": self.room_info,
            "table_no": self.table_no,
            "special_requests": self.special_requests,
            "deposit_required": self.deposit_required,
            "deposit_amount_fen": self.deposit_amount_fen,
            "deposit_paid": self.deposit_paid,
            "consumer_id": self.consumer_id,
            "status": self.status,
            "queue_id": self.queue_id,
            "order_id": self.order_id,
            "confirmed_by": self.confirmed_by,
            "cancel_reason": self.cancel_reason,
            "cancel_fee_fen": self.cancel_fee_fen,
            "no_show_recorded": self.no_show_recorded,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "arrived_at": self.arrived_at,
            "seated_at": self.seated_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
        }


class NoShowRecord(TenantBase):
    """爽约记录"""
    __tablename__ = "no_show_records"

    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reservation_id: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="关联预订业务ID",
    )

    __table_args__ = (
        Index("idx_no_show_phone", "phone"),
        {"comment": "顾客爽约记录"},
    )
