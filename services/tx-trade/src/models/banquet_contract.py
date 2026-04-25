"""宴会合同管理 ORM模型"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetContract(TenantBase):
    """宴会合同"""

    __tablename__ = "banquet_contracts"

    contract_no: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True, comment="BCT-XXXXXXXXXXXX"
    )
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    party_a_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="甲方-客户")
    party_a_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    party_a_id_no: Mapped[Optional[str]] = mapped_column(String(30))
    party_a_company: Mapped[Optional[str]] = mapped_column(String(200))
    party_b_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="乙方-餐厅")
    party_b_license: Mapped[Optional[str]] = mapped_column(String(50))
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_name: Mapped[Optional[str]] = mapped_column(String(200))
    venue_name: Mapped[Optional[str]] = mapped_column(String(100))
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_snapshot_json: Mapped[dict] = mapped_column(JSON, default=list, comment="签约时菜单快照")
    terms_json: Mapped[dict] = mapped_column(JSON, default=dict, comment="条款")
    total_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="合同总额(分)")
    deposit_ratio: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("30.00"), comment="定金比例%")
    deposit_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="定金(分)")
    payment_schedule_json: Mapped[dict] = mapped_column(JSON, default=list, comment="付款计划")
    signed_at: Mapped[Optional[datetime]] = mapped_column()
    signed_by_customer: Mapped[Optional[str]] = mapped_column(String(100))
    signed_by_staff: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    amendment_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_bct_banquet", "tenant_id", "banquet_id"),
        Index("idx_bct_status", "tenant_id", "status"),
        {"comment": "宴会合同"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "contract_no": self.contract_no,
            "banquet_id": str(self.banquet_id),
            "template_id": str(self.template_id) if self.template_id else None,
            "party_a_name": self.party_a_name,
            "party_a_phone": self.party_a_phone,
            "party_a_id_no": self.party_a_id_no,
            "party_a_company": self.party_a_company,
            "party_b_name": self.party_b_name,
            "party_b_license": self.party_b_license,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "event_name": self.event_name,
            "venue_name": self.venue_name,
            "table_count": self.table_count,
            "guest_count": self.guest_count,
            "menu_snapshot_json": self.menu_snapshot_json,
            "terms_json": self.terms_json,
            "total_fen": self.total_fen,
            "deposit_ratio": float(self.deposit_ratio) if self.deposit_ratio else None,
            "deposit_fen": self.deposit_fen,
            "payment_schedule_json": self.payment_schedule_json,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "signed_by_customer": self.signed_by_customer,
            "signed_by_staff": str(self.signed_by_staff) if self.signed_by_staff else None,
            "status": self.status,
            "amendment_count": self.amendment_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BanquetContractAmendment(TenantBase):
    """合同变更记录"""

    __tablename__ = "banquet_contract_amendments"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amendment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="menu/table_count/guest_count/date/venue/price/terms/other")
    old_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    new_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    price_diff_fen: Mapped[int] = mapped_column(Integer, default=0, comment="价格变动(分)")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="pending")

    __table_args__ = (
        Index("idx_bca_contract", "tenant_id", "contract_id"),
        {"comment": "合同变更记录"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "contract_id": str(self.contract_id),
            "amendment_no": self.amendment_no,
            "change_type": self.change_type,
            "old_value_json": self.old_value_json,
            "new_value_json": self.new_value_json,
            "reason": self.reason,
            "price_diff_fen": self.price_diff_fen,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
