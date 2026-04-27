"""开发者提现 ORM"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgePayout(TenantBase):
    __tablename__ = "forge_payouts"

    payout_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bank_account: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
