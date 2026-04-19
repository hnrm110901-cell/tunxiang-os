"""会计账期 ORM (W1.4)

迁移链:
  v270_accounting_periods — 建表 + CHECK + RLS + 索引

状态机:
    open ──close()──> closed
   closed ──reopen()──> open       (可重开, 留痕)
   closed ──lock()──> locked       (年结锁定)
   locked ──×──> ∅                 (不可重开, 只能追加红冲凭证)

审计字段 3 组 (closed_* / reopened_* / locked_*) 由状态机方法赋值,
DB CHECK 强制 status='closed' 时 closed_at/by 非空, status='locked' 时 locked_at/by 非空.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .cost_snapshot import Base


# 状态枚举 (应用层用, DB CHECK 同步)
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_LOCKED = "locked"
VALID_STATUSES = (STATUS_OPEN, STATUS_CLOSED, STATUS_LOCKED)


class AccountingPeriod(Base):
    """会计账期元数据 + 状态机.

    一个租户的每个月历月唯一一条. 由应用层 W1.4b 在首次写凭证时
    懒初始化 (open 状态).

    生效语义:
        voucher.voucher_date ∈ [period_start, period_end]
          AND period.status = 'open'
        → voucher 允许写
        否则 ValueError("账期已关, 请红冲").
    """
    __tablename__ = "accounting_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="租户 ID (RLS)."
    )

    period_year: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="账期年份 (2020-2100)."
    )
    period_month: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="账期月份 (1-12)."
    )
    period_start: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="账期首日."
    )
    period_end: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="账期末日."
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_OPEN,
        server_default=sa.text("'open'"),
        comment="open / closed / locked."
    )

    # closed 审计
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="月结时间. status='closed' 时 CHECK 非空."
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="月结操作员 UUID. status='closed' 时 CHECK 非空."
    )
    closed_reason: Mapped[str | None] = mapped_column(
        String(200),
        comment="月结原因/备注."
    )

    # reopened 审计 (closed → open)
    reopened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="重开时间 (仅 closed → open 填)."
    )
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="重开操作员 UUID."
    )
    reopened_reason: Mapped[str | None] = mapped_column(
        String(200),
        comment="重开原因 (应用层强制非空)."
    )

    # locked 审计 (year close)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="年结锁定时间. status='locked' 时 CHECK 非空."
    )
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="年结操作员 UUID."
    )
    locked_reason: Mapped[str | None] = mapped_column(
        String(200),
        comment="年结原因."
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "period_year", "period_month",
            name="uq_ap_tenant_year_month",
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'locked')",
            name="chk_ap_status_valid",
        ),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="chk_ap_month_range",
        ),
        CheckConstraint(
            "period_year BETWEEN 2020 AND 2100",
            name="chk_ap_year_range",
        ),
        CheckConstraint(
            "period_end >= period_start",
            name="chk_ap_date_range",
        ),
        CheckConstraint(
            "status != 'closed' "
            "OR (closed_at IS NOT NULL AND closed_by IS NOT NULL)",
            name="chk_ap_closed_audit",
        ),
        CheckConstraint(
            "status != 'locked' "
            "OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="chk_ap_locked_audit",
        ),
        Index(
            "ix_ap_tenant_open", "tenant_id",
            postgresql_where=sa.text("status = 'open'"),
        ),
        Index(
            "ix_ap_tenant_date_range",
            "tenant_id", "period_start", "period_end",
        ),
    )

    # ── 状态判定 ──────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    @property
    def is_closed(self) -> bool:
        return self.status == STATUS_CLOSED

    @property
    def is_locked(self) -> bool:
        return self.status == STATUS_LOCKED

    @property
    def is_writable(self) -> bool:
        """凭证是否可写入此账期 (只有 open 可)."""
        return self.status == STATUS_OPEN

    def contains_date(self, d: date) -> bool:
        return self.period_start <= d <= self.period_end

    # ── 状态机 ────────────────────────────────────────────────────────

    def close(
        self,
        operator_id: uuid.UUID,
        reason: str,
        closed_at: datetime | None = None,
    ) -> None:
        """月结: open → closed.

        前置: status=='open'.
        """
        if self.status != STATUS_OPEN:
            raise ValueError(
                f"账期 {self.period_year}-{self.period_month:02d} 状态 {self.status} "
                f"不支持月结 (需 open)"
            )
        if not reason or not reason.strip():
            raise ValueError("月结原因必填 (审计留痕)")

        self.status = STATUS_CLOSED
        self.closed_at = closed_at or _utcnow()
        self.closed_by = operator_id
        self.closed_reason = reason.strip()

    def reopen(
        self,
        operator_id: uuid.UUID,
        reason: str,
        reopened_at: datetime | None = None,
    ) -> None:
        """重开: closed → open. locked 不可重开.

        前置: status=='closed'.
        """
        if self.status == STATUS_LOCKED:
            raise ValueError(
                f"账期 {self.period_year}-{self.period_month:02d} 已年结锁定, "
                f"不可重开 (只能追加红冲凭证)"
            )
        if self.status != STATUS_CLOSED:
            raise ValueError(
                f"账期 {self.period_year}-{self.period_month:02d} 状态 {self.status} "
                f"不支持重开 (需 closed)"
            )
        if not reason or not reason.strip():
            raise ValueError("重开原因必填 (审计留痕)")

        self.status = STATUS_OPEN
        self.reopened_at = reopened_at or _utcnow()
        self.reopened_by = operator_id
        self.reopened_reason = reason.strip()

    def lock(
        self,
        operator_id: uuid.UUID,
        reason: str,
        locked_at: datetime | None = None,
    ) -> None:
        """年结锁定: closed → locked.

        前置: status=='closed' (必须先月结才能年结锁).
        """
        if self.status != STATUS_CLOSED:
            raise ValueError(
                f"账期 {self.period_year}-{self.period_month:02d} 状态 {self.status} "
                f"不支持年结锁定 (需先月结 closed)"
            )
        if not reason or not reason.strip():
            raise ValueError("年结锁定原因必填 (审计留痕)")

        self.status = STATUS_LOCKED
        self.locked_at = locked_at or _utcnow()
        self.locked_by = operator_id
        self.locked_reason = reason.strip()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "period_year": self.period_year,
            "period_month": self.period_month,
            "period_label": f"{self.period_year}-{self.period_month:02d}",
            "period_start": str(self.period_start),
            "period_end": str(self.period_end),
            "status": self.status,
            "is_writable": self.is_writable,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": str(self.closed_by) if self.closed_by else None,
            "closed_reason": self.closed_reason,
            "reopened_at": self.reopened_at.isoformat() if self.reopened_at else None,
            "reopened_by": str(self.reopened_by) if self.reopened_by else None,
            "reopened_reason": self.reopened_reason,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": str(self.locked_by) if self.locked_by else None,
            "locked_reason": self.locked_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 工具函数 ────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


def month_range(year: int, month: int) -> tuple[date, date]:
    """返回指定年月的首末日 (date, date).

    e.g. month_range(2026, 4) → (date(2026,4,1), date(2026,4,30))
    """
    if not (1 <= month <= 12):
        raise ValueError(f"月份非法: {month}")
    start = date(year, month, 1)
    # 月末: 下个月 1 号 - 1 天
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    end = date.fromordinal(next_month_first.toordinal() - 1)
    return start, end
