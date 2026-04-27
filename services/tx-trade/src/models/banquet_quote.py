"""宴会报价与套餐模板 ORM模型 — Phase 1"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class BanquetMenuTemplate(TenantBase):
    """宴会套餐模板"""

    __tablename__ = "banquet_menu_templates_v2"

    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="NULL=集团通用，非NULL=门店专属",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="economy/standard/premium/luxury/custom",
    )
    event_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="wedding/birthday/business/tour_group/conference/annual_party/memorial/other",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_per_table_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="每桌价格(分)",
    )
    price_per_person_fen: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="每人价格(分)",
    )
    min_table_count: Mapped[int] = mapped_column(Integer, default=1)
    max_table_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deposit_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.3000"),
        comment="定金比例，如0.3000=30%",
    )
    dish_list: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="菜品清单JSON数组",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_bmt_tenant_store", "tenant_id", "store_id"),
        Index("idx_bmt_tier", "tenant_id", "tier"),
        Index("idx_bmt_event_type", "tenant_id", "event_type"),
        {"comment": "宴会套餐模板"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id) if self.store_id else None,
            "name": self.name,
            "tier": self.tier,
            "event_type": self.event_type,
            "description": self.description,
            "price_per_table_fen": self.price_per_table_fen,
            "price_per_person_fen": self.price_per_person_fen,
            "min_table_count": self.min_table_count,
            "max_table_count": self.max_table_count,
            "deposit_rate": float(self.deposit_rate) if self.deposit_rate else None,
            "dish_list": self.dish_list,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetQuote(TenantBase):
    """宴会报价单"""

    __tablename__ = "banquet_quotes"

    quote_no: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
        comment="业务ID BQQ-XXXXXXXXXXXX",
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="报价版本号，同一线索可多次报价",
    )
    tier: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="economy/standard/premium/luxury/custom",
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_table_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="每桌单价(分)",
    )
    subtotal_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="小计=桌数x单价(分)",
    )
    service_charge_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="服务费(分)",
    )
    venue_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="场地费(分)",
    )
    decoration_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="布置费(分)",
    )
    other_fee_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="其他费用(分)",
    )
    discount_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="优惠减免(分)",
    )
    total_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="报价总价(分)",
    )
    deposit_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.3000"),
    )
    deposit_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="定金金额(分)",
    )
    cost_est_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="预估成本(分)",
    )
    margin_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        default=Decimal("0.0000"),
        comment="预估毛利率",
    )
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="报价有效期",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        index=True,
        comment="draft/sent/accepted/expired/rejected/superseded",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejected_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    items: Mapped[list["BanquetQuoteItem"]] = relationship(
        back_populates="quote",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_bq_lead", "tenant_id", "lead_id"),
        Index("idx_bq_store", "tenant_id", "store_id"),
        Index("idx_bq_status", "tenant_id", "status"),
        {"comment": "宴会报价单"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "quote_no": self.quote_no,
            "lead_id": str(self.lead_id),
            "store_id": str(self.store_id),
            "template_id": str(self.template_id) if self.template_id else None,
            "version": self.version,
            "tier": self.tier,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "table_count": self.table_count,
            "guest_count": self.guest_count,
            "price_per_table_fen": self.price_per_table_fen,
            "subtotal_fen": self.subtotal_fen,
            "service_charge_fen": self.service_charge_fen,
            "venue_fee_fen": self.venue_fee_fen,
            "decoration_fee_fen": self.decoration_fee_fen,
            "other_fee_fen": self.other_fee_fen,
            "discount_fen": self.discount_fen,
            "total_fen": self.total_fen,
            "deposit_rate": float(self.deposit_rate) if self.deposit_rate else None,
            "deposit_fen": self.deposit_fen,
            "cost_est_fen": self.cost_est_fen,
            "margin_rate": float(self.margin_rate) if self.margin_rate else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "rejected_reason": self.rejected_reason,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "items": [item.to_dict() for item in self.items] if self.items else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }


class BanquetQuoteItem(TenantBase):
    """宴会报价单菜品明细"""

    __tablename__ = "banquet_quote_items"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    dish_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联菜品ID，自定义项为NULL",
    )
    dish_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dish_category: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="cold/hot/soup/staple/dessert/drink/fruit",
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, comment="每桌份数")
    unit: Mapped[str] = mapped_column(String(20), default="道")
    unit_price_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="单价(分)",
    )
    subtotal_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="小计(分)",
    )
    is_signature: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否招牌菜",
    )
    is_optional: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否可选换菜",
    )
    replacement_dish_ids: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="可替换菜品ID列表",
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    quote: Mapped["BanquetQuote"] = relationship(back_populates="items")

    __table_args__ = (
        Index("idx_bqi_quote", "tenant_id", "quote_id"),
        {"comment": "宴会报价单菜品明细"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "quote_id": str(self.quote_id),
            "dish_id": str(self.dish_id) if self.dish_id else None,
            "dish_name": self.dish_name,
            "dish_category": self.dish_category,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price_fen": self.unit_price_fen,
            "subtotal_fen": self.subtotal_fen,
            "is_signature": self.is_signature,
            "is_optional": self.is_optional,
            "replacement_dish_ids": self.replacement_dish_ids,
            "sort_order": self.sort_order,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }
