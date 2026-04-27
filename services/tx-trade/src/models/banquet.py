"""宴会ORM模型 — 映射v004+v013+v160迁移表"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class BanquetLead(TenantBase):
    """宴会线索 — 13阶段流水线"""

    __tablename__ = "banquet_leads"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    consumer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_tables: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_guests: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_budget_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_per_table_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    special_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    referral_source: Mapped[str] = mapped_column(String(32), default="walk_in")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="lead")
    assigned_sales: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stage_history: Mapped[list | None] = mapped_column(JSON, nullable=True)


class BanquetContract(TenantBase):
    """宴会合同"""

    __tablename__ = "banquet_contracts"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    contracted_total_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deposit_rate: Mapped[float] = mapped_column(Float, nullable=False)
    deposit_required_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deposit_paid_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    deposit_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    terms: Mapped[dict] = mapped_column(JSON, nullable=False)
    menu_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    final_menu_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    menu_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    hall_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    settlement: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="contract")
    execution_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # v013 additions
    requisition_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class BanquetProposalRecord(TenantBase):
    """宴会方案（v013新建）"""

    __tablename__ = "banquet_proposals"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tiers: Mapped[list] = mapped_column(JSON, nullable=False)
    recommended_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)


class BanquetQuotation(TenantBase):
    """宴会报价单（v013新建）"""

    __tablename__ = "banquet_quotations"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    base_total_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    adjustment_total_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    final_total_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    margin_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    margin_rate: Mapped[float] = mapped_column(Float, default=0)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)


class BanquetChecklist(TenantBase):
    """宴会筹备检查清单"""

    __tablename__ = "banquet_checklists"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(8), nullable=False)
    phase_name: Mapped[str] = mapped_column(String(32), nullable=False)
    due_offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    responsible: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class BanquetFeedback(TenantBase):
    """宴会客户反馈（v013新建）"""

    __tablename__ = "banquet_feedbacks"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    satisfaction_score: Mapped[int] = mapped_column(Integer, nullable=False)
    satisfaction_level: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(nullable=True)


class BanquetCase(TenantBase):
    """宴会案例归档（v013新建）"""

    __tablename__ = "banquet_cases"

    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    contract_no: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False)
    final_total_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    satisfaction_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    highlights: Mapped[list | None] = mapped_column(JSON, nullable=True)
    menu_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)


# ─── v160: 宴席套餐模板引擎 ───────────────────────────────────────────────


class BanquetMenuTemplate(TenantBase):
    """宴席套餐模板主表 — 映射v160迁移"""

    __tablename__ = "banquet_menu_templates"

    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="NULL=集团通用，非NULL=门店专属"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="wedding/business/birthday/festival/other"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    guest_count_min: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    guest_count_max: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    price_per_table_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_per_person_fen: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deposit_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.3"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    items: Mapped[list["BanquetTemplateItem"]] = relationship(back_populates="template", lazy="selectin")


class BanquetTemplateItem(TenantBase):
    """套餐模板菜品明细 — 映射v160迁移"""

    __tablename__ = "banquet_template_items"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("banquet_menu_templates.id"),
        nullable=False,
        index=True,
    )
    dish_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dish_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="cold/hot/soup/staple/dessert/drink"
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="道")
    is_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template: Mapped["BanquetMenuTemplate"] = relationship(back_populates="items")
