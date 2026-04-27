"""宴会桌组管理 ORM模型 — Phase 1"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetTableGroup(TenantBase):
    """宴会桌组 — 将多张桌台编组为一个宴会桌组"""

    __tablename__ = "banquet_table_groups"

    banquet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="关联宴会订单ID",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    venue_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联场地ID",
    )
    group_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="桌组名称，如'主桌区A'",
    )
    group_type: Mapped[str] = mapped_column(
        String(20),
        default="standard",
        comment="vip/standard/backup",
    )
    table_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        comment="桌台ID列表",
    )
    table_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="桌台数量",
    )
    guest_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="本组预计人数",
    )
    menu_tier: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="本组菜单档次 economy/standard/premium/luxury/custom",
    )
    quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联报价单ID",
    )
    per_table_price_fen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="本组每桌价格(分)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="planned",
        comment="planned/set_up/in_use/cleared",
    )
    set_up_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="摆台完成时间",
    )
    in_use_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始用餐时间",
    )
    cleared_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="清台完成时间",
    )
    special_requirements: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="特殊要求，如主桌加花/红毯通道",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_btg_banquet", "tenant_id", "banquet_id"),
        Index("idx_btg_store", "tenant_id", "store_id"),
        Index("idx_btg_status", "tenant_id", "status"),
        {"comment": "宴会桌组"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "banquet_id": str(self.banquet_id),
            "store_id": str(self.store_id),
            "venue_id": str(self.venue_id) if self.venue_id else None,
            "group_name": self.group_name,
            "group_type": self.group_type,
            "table_ids": self.table_ids,
            "table_count": self.table_count,
            "guest_count": self.guest_count,
            "menu_tier": self.menu_tier,
            "quote_id": str(self.quote_id) if self.quote_id else None,
            "per_table_price_fen": self.per_table_price_fen,
            "status": self.status,
            "set_up_at": self.set_up_at.isoformat() if self.set_up_at else None,
            "in_use_at": self.in_use_at.isoformat() if self.in_use_at else None,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "special_requirements": self.special_requirements,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
        }
