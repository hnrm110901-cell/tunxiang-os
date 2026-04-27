"""中央厨房 ORM 模型 — 生产计划 / 生产任务 / 配送行程 / 配送明细

所有模型继承 TenantBase，自带 id / tenant_id / created_at / updated_at / is_deleted。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class ProductionPlanORM(TenantBase):
    """生产计划 — 中央厨房按日汇总各门店需求后生成"""

    __tablename__ = "production_plans"

    kitchen_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="中央厨房 ID")
    plan_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="生产日期")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="draft/confirmed/in_progress/completed/cancelled",
    )
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="汇总食材种类数")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, comment="创建人 ID")

    # relationships
    tasks: Mapped[list[ProductionTaskORM]] = relationship(
        "ProductionTaskORM",
        back_populates="plan",
        lazy="selectin",
    )
    trips: Mapped[list[DeliveryTripORM]] = relationship(
        "DeliveryTripORM",
        back_populates="plan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_production_plans_tenant_kitchen", "tenant_id", "kitchen_id"),
        Index("ix_production_plans_tenant_date", "tenant_id", "plan_date"),
    )


class ProductionTaskORM(TenantBase):
    """生产任务 — 每条食材加工对应一个任务"""

    __tablename__ = "production_tasks"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="食材 ID")
    planned_qty: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False, comment="计划加工量")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="单位")
    assigned_station: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="加工档口")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending/processing/done",
    )
    actual_qty: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True, comment="实际产量")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # relationships
    plan: Mapped[ProductionPlanORM] = relationship(
        "ProductionPlanORM",
        back_populates="tasks",
    )

    __table_args__ = (Index("ix_production_tasks_tenant_plan", "tenant_id", "plan_id"),)


class DeliveryTripORM(TenantBase):
    """配送行程 — 一次出车覆盖多个门店"""

    __tablename__ = "delivery_trips"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    trip_no: Mapped[str] = mapped_column(String(30), nullable=False, comment="配送单号 TRP-YYMMDD-NN")
    driver_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="司机姓名")
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="车牌号")
    departure_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending/departed/completed/cancelled",
    )
    route_sequence: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="[{store_id, sequence, address, lat, lng}]"
    )

    # relationships
    plan: Mapped[ProductionPlanORM] = relationship(
        "ProductionPlanORM",
        back_populates="trips",
    )
    items: Mapped[list[DeliveryItemORM]] = relationship(
        "DeliveryItemORM",
        back_populates="trip",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_delivery_trips_tenant_plan", "tenant_id", "plan_id"),)


class DeliveryItemORM(TenantBase):
    """配送明细 — 每条食材 x 门店对应一条"""

    __tablename__ = "delivery_items"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("delivery_trips.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="门店 ID")
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="食材 ID")
    planned_qty: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False, comment="计划配送量")
    received_qty: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True, comment="实收量")
    variance_qty: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True, comment="差异量")
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending/delivered/signed/disputed",
    )

    # relationships
    trip: Mapped[DeliveryTripORM] = relationship(
        "DeliveryTripORM",
        back_populates="items",
    )

    __table_args__ = (
        Index("ix_delivery_items_tenant_trip", "tenant_id", "trip_id"),
        Index("ix_delivery_items_tenant_store", "tenant_id", "store_id"),
    )
