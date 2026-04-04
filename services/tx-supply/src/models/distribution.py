"""配送管理 ORM 模型

表：
  distribution_warehouses  — 仓库配置（含坐标）
  distribution_plans       — 配送计划
  distribution_trips       — 配送行程（一个计划可拆多趟）
  distribution_items       — 配送明细（行程-门店-SKU 级别）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class DistributionWarehouse(TenantBase):
    """仓库配置"""

    __tablename__ = "distribution_warehouses"

    warehouse_name: Mapped[str] = mapped_column(String(200), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lng: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # relationship
    plans: Mapped[list[DistributionPlan]] = relationship(
        back_populates="warehouse", lazy="selectin",
    )


class DistributionPlan(TenantBase):
    """配送计划"""

    __tablename__ = "distribution_plans"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distribution_warehouses.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned",
    )
    store_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    route_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # relationships
    warehouse: Mapped[DistributionWarehouse] = relationship(
        back_populates="plans", lazy="selectin",
    )
    trips: Mapped[list[DistributionTrip]] = relationship(
        back_populates="plan", lazy="selectin",
    )


class DistributionTrip(TenantBase):
    """配送行程（一个 plan 的一次门店送达记录）"""

    __tablename__ = "distribution_trips"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distribution_plans.id"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # relationships
    plan: Mapped[DistributionPlan] = relationship(
        back_populates="trips", lazy="selectin",
    )
    items: Mapped[list[DistributionItem]] = relationship(
        back_populates="trip", lazy="selectin",
    )


class DistributionItem(TenantBase):
    """配送明细（行程级别的 SKU 明细）"""

    __tablename__ = "distribution_items"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distribution_trips.id"),
        nullable=False,
    )
    item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(
        Numeric(10, 3), nullable=False, default=0,
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    received_quantity: Mapped[float | None] = mapped_column(
        Numeric(10, 3), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # relationship
    trip: Mapped[DistributionTrip] = relationship(
        back_populates="items", lazy="selectin",
    )
