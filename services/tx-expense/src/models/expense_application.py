"""
费用申请 ORM 模型
包含：ExpenseCategory（科目树）、ExpenseScenario（场景）、
     ExpenseApplication（申请主表）、ExpenseItem（明细行）、ExpenseAttachment（附件）

设计说明：
- 所有金额字段单位为分(fen)，整数存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离（tenant_id + is_deleted 由基类提供）
- ExpenseCategory 支持自引用层级（科目树），parent_id nullable
- ExpenseApplication.metadata 保留扩展字段，避免频繁 DDL 变更
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

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
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase
from .expense_enums import ExpenseCategoryCode, ExpenseScenarioCode, ExpenseStatus


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseCategory — 费用科目树（支持自引用层级）
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseCategory(TenantBase):
    """
    费用科目树
    支持自引用多级层级（如：差旅费 → 交通费 → 机票）。
    is_system=True 表示系统预置科目，不允许租户删除。
    """
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="科目名称"
    )
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="科目代码，参见 ExpenseCategoryCode 枚举"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="科目说明"
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父科目ID，NULL 表示顶级科目"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="排序权重，越小越靠前"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="是否系统预置科目（系统科目不可删除）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )

    # 关系：自引用父子层级
    parent: Mapped[Optional["ExpenseCategory"]] = relationship(
        "ExpenseCategory",
        remote_side="ExpenseCategory.id",
        back_populates="children",
        foreign_keys=[parent_id],
    )
    children: Mapped[List["ExpenseCategory"]] = relationship(
        "ExpenseCategory",
        back_populates="parent",
        foreign_keys=[parent_id],
        cascade="all, delete-orphan",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseScenario — 费用申请场景预置
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseScenario(TenantBase):
    """
    费用申请场景预置（10个预置场景）
    每个场景对应一类费用申请，定义默认科目、必填字段和审批路由提示。
    """
    __tablename__ = "expense_scenarios"

    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True,
        comment="场景代码，参见 ExpenseScenarioCode 枚举"
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="场景名称，如「日常费用报销」"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="场景说明"
    )
    icon: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="前端图标标识符"
    )
    default_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_categories.id", ondelete="SET NULL"),
        nullable=True,
        comment="默认费用科目ID，申请时预填充"
    )
    required_fields: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="该场景必填字段列表，如 [\"purpose\", \"invoice_count\"]"
    )
    approval_routing_hint: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="审批路由提示，如 amount_based / scenario_fixed"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="排序权重"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )

    # 注意：TenantBase 已提供 created_at，此处无需重复声明


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseApplication — 费用申请主表
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseApplication(TenantBase):
    """
    费用申请主表
    一张单据对应一个申请人的一次费用申请，包含若干明细行（ExpenseItem）。
    total_amount 单位为分(fen)，展示时除以100转元。
    """
    __tablename__ = "expense_applications"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属品牌ID"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属门店ID"
    )
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="申请人员工ID"
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_scenarios.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="申请场景ID"
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="申请标题"
    )
    total_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="申请总金额，单位：分(fen)，展示时除以100转元"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", comment="货币代码，默认 CNY"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExpenseStatus.DRAFT.value,
        index=True, comment="申请状态，参见 ExpenseStatus 枚举"
    )
    legal_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="付款主体法人ID（预留，对接 tx-finance 法人账户）"
    )
    purpose: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="费用用途说明"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="申请人备注"
    )
    metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="扩展字段，存储场景特定的附加信息（如出差目的地、招待人数等）"
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="提交时间"
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批通过时间"
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批驳回时间"
    )

    # 关系
    scenario: Mapped["ExpenseScenario"] = relationship(
        "ExpenseScenario", foreign_keys=[scenario_id], lazy="select"
    )
    items: Mapped[List["ExpenseItem"]] = relationship(
        "ExpenseItem",
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="select",
    )
    attachments: Mapped[List["ExpenseAttachment"]] = relationship(
        "ExpenseAttachment",
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseItem — 费用明细行
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseItem(TenantBase):
    """
    费用明细行
    一条申请可包含多个明细行，每行对应一笔费用支出。
    amount 单位为分(fen)。
    """
    __tablename__ = "expense_items"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属申请ID"
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="费用科目ID"
    )
    description: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="费用描述"
    )
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="明细金额，单位：分(fen)，展示时除以100转元"
    )
    quantity: Mapped[Numeric] = mapped_column(
        Numeric(10, 3), nullable=False, default=1,
        comment="数量（如天数、件数，支持小数）"
    )
    unit: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="单位，如「天」「次」「件」"
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联发票ID（预留P1阶段对接发票模块）"
    )
    expense_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="费用发生日期"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="明细备注"
    )

    # 关系
    application: Mapped["ExpenseApplication"] = relationship(
        "ExpenseApplication", back_populates="items", foreign_keys=[application_id]
    )
    category: Mapped["ExpenseCategory"] = relationship(
        "ExpenseCategory", foreign_keys=[category_id], lazy="select"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseAttachment — 费用凭证附件
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseAttachment(TenantBase):
    """
    费用凭证附件（发票扫描件、收据照片等）
    上传路径存储相对 URL，实际文件由对象存储（腾讯云 COS）管理。
    """
    __tablename__ = "expense_attachments"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属申请ID"
    )
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始文件名"
    )
    file_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="文件存储 URL（COS 对象路径）"
    )
    file_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="文件 MIME 类型，如 image/jpeg、application/pdf"
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="上传人员工ID"
    )

    # 关系
    application: Mapped["ExpenseApplication"] = relationship(
        "ExpenseApplication", back_populates="attachments", foreign_keys=[application_id]
    )
