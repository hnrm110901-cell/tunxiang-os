"""中央厨房生产计划相关模型

# SCHEMA SQL:
# CREATE TABLE production_plans (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     kitchen_id UUID NOT NULL,           -- 中央厨房ID
#     plan_date DATE NOT NULL,
#     status VARCHAR(20) DEFAULT 'draft', -- draft/confirmed/in_progress/completed
#     total_items INTEGER DEFAULT 0,
#     created_by UUID,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE production_tasks (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     plan_id UUID NOT NULL REFERENCES production_plans(id),
#     ingredient_id UUID NOT NULL,
#     planned_qty NUMERIC(10,3) NOT NULL,
#     unit VARCHAR(20) NOT NULL,
#     assigned_station VARCHAR(50),        -- 加工档口
#     status VARCHAR(20) DEFAULT 'pending', -- pending/processing/done
#     actual_qty NUMERIC(10,3),
#     started_at TIMESTAMPTZ,
#     completed_at TIMESTAMPTZ
# );
#
# CREATE TABLE delivery_trips (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     plan_id UUID NOT NULL REFERENCES production_plans(id),
#     trip_no VARCHAR(30) NOT NULL,
#     driver_name VARCHAR(50),
#     vehicle_plate VARCHAR(20),
#     departure_time TIMESTAMPTZ,
#     status VARCHAR(20) DEFAULT 'pending',
#     route_sequence JSONB,               -- [{store_id, sequence, address}]
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE TABLE delivery_items (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     trip_id UUID NOT NULL REFERENCES delivery_trips(id),
#     store_id UUID NOT NULL,
#     ingredient_id UUID NOT NULL,
#     planned_qty NUMERIC(10,3) NOT NULL,
#     received_qty NUMERIC(10,3),
#     variance_qty NUMERIC(10,3),
#     received_at TIMESTAMPTZ,
#     status VARCHAR(20) DEFAULT 'pending' -- pending/delivered/signed/disputed
# );
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 状态常量 ───

PLAN_STATUSES = ("draft", "confirmed", "in_progress", "completed", "cancelled")
TASK_STATUSES = ("pending", "processing", "done")
TRIP_STATUSES = ("pending", "departed", "completed", "cancelled")
DELIVERY_ITEM_STATUSES = ("pending", "delivered", "signed", "disputed")


@dataclass
class ProductionPlan:
    id: str
    tenant_id: str
    kitchen_id: str
    plan_date: str          # ISO date string: YYYY-MM-DD
    status: str = "draft"
    total_items: int = 0
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    tasks: List["ProductionTask"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "kitchen_id": self.kitchen_id,
            "plan_date": self.plan_date,
            "status": self.status,
            "total_items": self.total_items,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "tasks": [t.to_dict() for t in self.tasks],
        }


@dataclass
class ProductionTask:
    id: str
    tenant_id: str
    plan_id: str
    ingredient_id: str
    planned_qty: float
    unit: str
    assigned_station: Optional[str] = None
    status: str = "pending"
    actual_qty: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "plan_id": self.plan_id,
            "ingredient_id": self.ingredient_id,
            "planned_qty": self.planned_qty,
            "unit": self.unit,
            "assigned_station": self.assigned_station,
            "status": self.status,
            "actual_qty": self.actual_qty,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class DeliveryTrip:
    id: str
    tenant_id: str
    plan_id: str
    trip_no: str
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    departure_time: Optional[str] = None
    status: str = "pending"
    route_sequence: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    items: List["DeliveryItem"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "plan_id": self.plan_id,
            "trip_no": self.trip_no,
            "driver_name": self.driver_name,
            "vehicle_plate": self.vehicle_plate,
            "departure_time": self.departure_time,
            "status": self.status,
            "route_sequence": self.route_sequence,
            "created_at": self.created_at,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class DeliveryItem:
    id: str
    tenant_id: str
    trip_id: str
    store_id: str
    ingredient_id: str
    planned_qty: float
    received_qty: Optional[float] = None
    variance_qty: Optional[float] = None
    received_at: Optional[str] = None
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "trip_id": self.trip_id,
            "store_id": self.store_id,
            "ingredient_id": self.ingredient_id,
            "planned_qty": self.planned_qty,
            "received_qty": self.received_qty,
            "variance_qty": self.variance_qty,
            "received_at": self.received_at,
            "status": self.status,
        }
