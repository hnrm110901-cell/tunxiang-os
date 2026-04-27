"""库位/库区/温区编码 — TASK-2 仓储库存细化 ORM + Schema

ORM（SQLAlchemy 2.0）：
  WarehouseZone                — 库区
  WarehouseLocation            — 库位
  IngredientLocationBinding    — 食材→默认库位
  InventoryByLocation          — 按库位粒度的实时库存

Pydantic V2 Schema：
  各表的 Create / Update / Read 模型 + 业务请求体（auto-allocate / move）

枚举：
  TemperatureType  — NORMAL / REFRIGERATED / FROZEN / LIVE_SEAFOOD
  AbcClass         — A / B / C
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# ─────────────────────────────────────────────────────────────────────────────
# 枚举
# ─────────────────────────────────────────────────────────────────────────────


class TemperatureType(str, Enum):
    """温区类型（与 warehouse_zones.temperature_type CHECK 约束一致）"""

    NORMAL = "NORMAL"  # 常温（米面油干货）
    REFRIGERATED = "REFRIGERATED"  # 冷藏（0~10℃）
    FROZEN = "FROZEN"  # 冷冻（-18℃ 以下）
    LIVE_SEAFOOD = "LIVE_SEAFOOD"  # 活鲜（鱼缸/海鲜池）


class AbcClass(str, Enum):
    """ABC 周转优先级"""

    A = "A"  # 高频
    B = "B"  # 中频
    C = "C"  # 低频


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型
# ─────────────────────────────────────────────────────────────────────────────


class WarehouseZone(TenantBase):
    """库区（warehouse_zones）"""

    __tablename__ = "warehouse_zones"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone_code: Mapped[str] = mapped_column(String(32), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature_type: Mapped[str] = mapped_column(String(24), nullable=False)
    min_temp_celsius: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    max_temp_celsius: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WarehouseLocation(TenantBase):
    """库位（warehouse_locations）"""

    __tablename__ = "warehouse_locations"

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_zones.id"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_code: Mapped[str] = mapped_column(String(48), nullable=False)
    aisle: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    rack: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    shelf: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    abc_class: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    max_capacity_units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class IngredientLocationBinding(TenantBase):
    """食材→默认库位（ingredient_location_bindings）"""

    __tablename__ = "ingredient_location_bindings"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id"),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    bound_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class InventoryByLocation(TenantBase):
    """按库位粒度的实时库存（inventory_by_location）

    注意：此表无 is_deleted 字段（库存清零即可），但继承 TenantBase 仍带 is_deleted；
    实际查询通常忽略该字段（迁移中物理表也未默认 is_deleted=FALSE 过滤）。
    """

    __tablename__ = "inventory_by_location"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id"),
        nullable=False,
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=0
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=0
    )
    last_in_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic V2 Schemas
# ─────────────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ── WarehouseZone ──


class ZoneCreate(_BaseSchema):
    store_id: str
    zone_code: str = Field(min_length=1, max_length=32)
    zone_name: str = Field(min_length=1, max_length=64)
    temperature_type: TemperatureType
    min_temp_celsius: Optional[Decimal] = None
    max_temp_celsius: Optional[Decimal] = None
    description: Optional[str] = None
    enabled: bool = True


class ZoneUpdate(_BaseSchema):
    zone_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    temperature_type: Optional[TemperatureType] = None
    min_temp_celsius: Optional[Decimal] = None
    max_temp_celsius: Optional[Decimal] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class ZoneRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    zone_code: str
    zone_name: str
    temperature_type: str
    min_temp_celsius: Optional[Decimal]
    max_temp_celsius: Optional[Decimal]
    description: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


# ── WarehouseLocation ──


class LocationCreate(_BaseSchema):
    zone_id: str
    store_id: str
    location_code: str = Field(min_length=1, max_length=48)
    aisle: Optional[str] = Field(default=None, max_length=8)
    rack: Optional[str] = Field(default=None, max_length=8)
    shelf: Optional[str] = Field(default=None, max_length=8)
    abc_class: Optional[AbcClass] = None
    max_capacity_units: Optional[int] = Field(default=None, ge=0)
    enabled: bool = True


class LocationRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    zone_id: uuid.UUID
    store_id: uuid.UUID
    location_code: str
    aisle: Optional[str]
    rack: Optional[str]
    shelf: Optional[str]
    abc_class: Optional[str]
    max_capacity_units: Optional[int]
    enabled: bool
    created_at: datetime
    updated_at: datetime


# ── Bindings ──


class BindIngredientRequest(_BaseSchema):
    ingredient_id: str
    is_primary: bool = True
    bound_by: Optional[str] = None


# ── 业务请求体 ──


class AutoAllocateRequest(_BaseSchema):
    """入库时自动分配库位"""

    ingredient_id: str
    store_id: str
    quantity: Decimal = Field(gt=0)
    batch_no: Optional[str] = None
    expiry_date: Optional[date] = None
    # 食材温区类目，如 "seafood" / "meat" / "vegetable" / "dry_goods"
    # 用于匹配库区的 temperature_type；上层（receiving 服务）传入。
    ingredient_category: Optional[str] = None


class MoveBetweenLocationsRequest(_BaseSchema):
    """库位间转移"""

    from_location_id: str
    to_location_id: str
    ingredient_id: str
    quantity: Decimal = Field(gt=0)
    batch_no: Optional[str] = None
    operator_id: Optional[str] = None


class InventoryByLocationRead(_BaseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    location_id: uuid.UUID
    ingredient_id: uuid.UUID
    batch_no: str
    quantity: Decimal
    reserved_quantity: Decimal
    last_in_at: Optional[datetime]
    last_out_at: Optional[datetime]
    expiry_date: Optional[date]
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# 食材类目 → 兼容温区映射（用于 auto_allocate 校验）
# 该映射可由上层覆盖；下方为缺省值。
# ─────────────────────────────────────────────────────────────────────────────


CATEGORY_TO_TEMPERATURE_TYPES: dict[str, set[TemperatureType]] = {
    # 海鲜：必须放活鲜或冷冻区
    "seafood": {TemperatureType.LIVE_SEAFOOD, TemperatureType.FROZEN},
    "live_seafood": {TemperatureType.LIVE_SEAFOOD},
    # 肉类：冷藏或冷冻
    "meat": {TemperatureType.REFRIGERATED, TemperatureType.FROZEN},
    "poultry": {TemperatureType.REFRIGERATED, TemperatureType.FROZEN},
    # 蔬菜/蛋/乳：冷藏
    "vegetable": {TemperatureType.REFRIGERATED},
    "dairy": {TemperatureType.REFRIGERATED},
    "egg": {TemperatureType.REFRIGERATED},
    # 干货/调料：常温
    "dry_goods": {TemperatureType.NORMAL},
    "seasoning": {TemperatureType.NORMAL},
    "grain": {TemperatureType.NORMAL},
    # 冷冻品：冷冻
    "frozen": {TemperatureType.FROZEN},
}
