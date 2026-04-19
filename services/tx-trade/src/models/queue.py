"""排队叫号模型 — 6状态机，支持VIP优先与美团同步"""

import uuid

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

from .enums import QueueSource, QueueStatus


class QueueEntry(TenantBase):
    """排队记录"""

    __tablename__ = "queue_entries"

    queue_id: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
        comment="业务ID如Q-XXXXXXXXXXXX",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    queue_number: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="排队号如A001",
    )
    prefix: Mapped[str] = mapped_column(String(1), nullable=False, comment="桌型前缀A/B/C")
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="序号")

    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=QueueSource.walk_in.value,
    )
    vip_priority: Mapped[bool] = mapped_column(Boolean, default=False)
    reservation_id: Mapped[str | None] = mapped_column(String(20), comment="关联预订业务ID")

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=QueueStatus.waiting.value,
        index=True,
    )
    priority_ts: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="优先级时间戳(VIP前移)",
    )

    # 时间线
    taken_at: Mapped[str] = mapped_column(String(50), nullable=False)
    called_at: Mapped[str | None] = mapped_column(String(50))
    arrived_at: Mapped[str | None] = mapped_column(String(50))
    seated_at: Mapped[str | None] = mapped_column(String(50))
    skipped_at: Mapped[str | None] = mapped_column(String(50))
    cancelled_at: Mapped[str | None] = mapped_column(String(50))

    # 桌台
    table_no: Mapped[str | None] = mapped_column(String(20))

    # 原因
    skip_reason: Mapped[str | None] = mapped_column(String(200))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))

    # 通知
    notification_count: Mapped[int] = mapped_column(Integer, default=0)

    # 日期（便于按天查询）
    date: Mapped[str] = mapped_column(String(10), nullable=False, comment="YYYY-MM-DD")

    __table_args__ = (
        Index("idx_queue_store_date", "store_id", "date"),
        Index("idx_queue_store_status", "store_id", "status"),
        Index("idx_queue_store_date_prefix", "store_id", "date", "prefix"),
        {"comment": "排队叫号记录"},
    )

    def to_dict(self) -> dict:
        """转为业务字典（保持与原内存结构兼容）"""
        return {
            "queue_id": self.queue_id,
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "queue_number": self.queue_number,
            "prefix": self.prefix,
            "seq": self.seq,
            "customer_name": self.customer_name,
            "phone": self.phone,
            "party_size": self.party_size,
            "source": self.source,
            "vip_priority": self.vip_priority,
            "reservation_id": self.reservation_id,
            "status": self.status,
            "priority_ts": self.priority_ts,
            "taken_at": self.taken_at,
            "called_at": self.called_at,
            "arrived_at": self.arrived_at,
            "seated_at": self.seated_at,
            "skipped_at": self.skipped_at,
            "cancelled_at": self.cancelled_at,
            "table_no": self.table_no,
            "skip_reason": self.skip_reason,
            "cancel_reason": self.cancel_reason,
            "notification_count": self.notification_count,
            "date": self.date,
        }


class QueueCounter(TenantBase):
    """排队号计数器 — 按门店+日期+前缀记录当日最大序号"""

    __tablename__ = "queue_counters"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False, comment="YYYY-MM-DD")
    prefix: Mapped[str] = mapped_column(String(1), nullable=False, comment="A/B/C")
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # 修复: 唯一约束必须包含 tenant_id，否则不同租户的计数器会冲突
        Index("uq_queue_counter", "tenant_id", "store_id", "date", "prefix", unique=True),
        {"comment": "排队号当日计数器"},
    )
