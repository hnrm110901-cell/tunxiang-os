"""厨师绩效日汇总模型"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ChefPerformanceDaily(TenantBase):
    __tablename__ = "chef_performance_daily"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    perf_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    dish_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dish_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    avg_cook_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rush_handled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remake_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
