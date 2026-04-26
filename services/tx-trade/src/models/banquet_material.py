"""宴会原料分解 + 采购单 ORM模型"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetMaterialRequirement(TenantBase):
    """宴会原料需求"""

    __tablename__ = "banquet_material_requirements"

    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ingredient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), comment="蔬菜/肉类/海鲜/干货/调料/酒水")
    required_qty: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_cost_fen: Mapped[int] = mapped_column(Integer, default=0, comment="单价(分)")
    total_cost_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总成本(分)")
    source: Mapped[str] = mapped_column(String(20), default="purchase", comment="inventory/purchase/both")
    inventory_available: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    inventory_reserved: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    purchase_needed: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="calculated", index=True)

    __table_args__ = (
        Index("idx_bmr_banquet", "tenant_id", "banquet_id"),
        Index("idx_bmr_status", "tenant_id", "status"),
        {"comment": "宴会原料需求"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "banquet_id": str(self.banquet_id),
            "ingredient_id": str(self.ingredient_id) if self.ingredient_id else None,
            "ingredient_name": self.ingredient_name,
            "category": self.category,
            "required_qty": float(self.required_qty),
            "unit": self.unit,
            "unit_cost_fen": self.unit_cost_fen,
            "total_cost_fen": self.total_cost_fen,
            "source": self.source,
            "inventory_available": float(self.inventory_available),
            "inventory_reserved": float(self.inventory_reserved),
            "purchase_needed": float(self.purchase_needed),
            "purchase_order_id": str(self.purchase_order_id) if self.purchase_order_id else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BanquetPurchaseOrder(TenantBase):
    """宴会专用采购单"""

    __tablename__ = "banquet_purchase_orders"

    po_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True, comment="BPO-XXXXXXXXXXXX")
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200))
    items_json: Mapped[dict] = mapped_column(JSON, default=list)
    total_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总额(分)")
    required_by: Mapped[date] = mapped_column(Date, nullable=False, comment="要求到货日")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    linked_supply_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), comment="关联tx-supply")
    submitted_at: Mapped[Optional[datetime]] = mapped_column()
    received_at: Mapped[Optional[datetime]] = mapped_column()
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_bpo_banquet", "tenant_id", "banquet_id"),
        Index("idx_bpo_status", "tenant_id", "status"),
        {"comment": "宴会专用采购单"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "po_no": self.po_no,
            "banquet_id": str(self.banquet_id),
            "store_id": str(self.store_id),
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "supplier_name": self.supplier_name,
            "items_json": self.items_json,
            "total_fen": self.total_fen,
            "required_by": self.required_by.isoformat() if self.required_by else None,
            "status": self.status,
            "linked_supply_order_id": str(self.linked_supply_order_id) if self.linked_supply_order_id else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
