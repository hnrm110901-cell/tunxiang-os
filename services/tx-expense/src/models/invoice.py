"""
发票 ORM 模型
Invoice:     发票主档（OCR识别 + 金税核验 + 集团去重 + 科目建议）
InvoiceItem: 发票明细行（货物/服务明细）

核心设计：
- dedup_hash = SHA-256(invoice_code + invoice_number + total_amount)
  用于集团级跨品牌跨门店去重，同一张发票全集团只能报销一次
- verify_status 为 verified_fake 时高亮显示，但不自动驳回（由审批人决定）
- 所有金额字段单位为分(fen)
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
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase
from .expense_enums import InvoiceType, OcrStatus, OcrProvider, VerifyStatus


# ─────────────────────────────────────────────────────────────────────────────
# Invoice — 发票主档
# ─────────────────────────────────────────────────────────────────────────────

class Invoice(TenantBase):
    """
    发票主档
    支持 OCR 识别、金税核验、集团级去重、AI 科目建议。
    所有金额字段单位为分(fen)，展示时除以100转元。
    verify_status=verified_fake 时前端高亮警告，不触发自动驳回，由审批人人工决策。
    """
    __tablename__ = "invoices"

    # ── 归属维度 ─────────────────────────────────────────────────────────────
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属品牌ID"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属门店ID"
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="上传人员工ID"
    )

    # ── 关联费用申请（nullable，发票可先上传后关联申请）────────────────────────
    application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联费用申请ID，允许为空（先上传发票后关联申请）"
    )

    # ── 发票基础信息 ──────────────────────────────────────────────────────────
    invoice_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InvoiceType.VAT_GENERAL.value,
        comment="发票类型，参见 InvoiceType 枚举"
    )
    invoice_code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True, comment="发票代码（增值税发票10/12位代码）"
    )
    invoice_number: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True, comment="发票号码（8位流水号）"
    )
    invoice_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="开票日期"
    )

    # ── 销售方信息 ────────────────────────────────────────────────────────────
    seller_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="销售方名称"
    )
    seller_tax_id: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="销售方纳税人识别号（18位统一社会信用代码）"
    )

    # ── 购买方信息 ────────────────────────────────────────────────────────────
    buyer_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="购买方名称"
    )
    buyer_tax_id: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="购买方纳税人识别号（18位统一社会信用代码）"
    )

    # ── 金额字段（单位：分） ───────────────────────────────────────────────────
    total_amount: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="价税合计，单位：分(fen)，展示时除以100转元"
    )
    tax_amount: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="税额合计，单位：分(fen)，展示时除以100转元"
    )
    amount_without_tax: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="不含税金额合计，单位：分(fen)，展示时除以100转元"
    )
    tax_rate: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(5, 4), nullable=True, comment="税率（如0.13表示13%），明细行不一致时取主行"
    )

    # ── 文件信息 ──────────────────────────────────────────────────────────────
    file_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="文件存储 URL（COS 对象路径）"
    )
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始文件名"
    )
    file_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="文件 MIME 类型，如 image/jpeg、application/pdf"
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )
    thumbnail_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True, comment="缩略图 URL（PDF/图片压缩预览）"
    )

    # ── OCR 识别 ──────────────────────────────────────────────────────────────
    ocr_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OcrStatus.PENDING.value,
        index=True, comment="OCR 识别状态，参见 OcrStatus 枚举"
    )
    ocr_provider: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="OCR 服务提供商，参见 OcrProvider 枚举"
    )
    ocr_raw_result: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="OCR 服务原始返回结果（JSON），用于审计和重新解析"
    )
    ocr_confidence: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="OCR 整体置信度（0-1），低于阈值时触发人工复核"
    )

    # ── 金税核验 ──────────────────────────────────────────────────────────────
    verify_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VerifyStatus.PENDING.value,
        index=True,
        comment=(
            "金税核验状态，参见 VerifyStatus 枚举。"
            "verified_fake 时前端高亮警告，不自动驳回，由审批人人工决策。"
        )
    )
    verify_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="核验完成时间"
    )
    verify_response: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="金税核验接口原始返回（JSON），用于审计留痕"
    )

    # ── 集团去重 ──────────────────────────────────────────────────────────────
    dedup_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment=(
            "集团去重哈希，算法：SHA-256(invoice_code + invoice_number + total_amount)。"
            "全集团唯一，同一张发票跨品牌跨门店只能报销一次。"
        )
    )
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="是否为重复发票（dedup_hash 碰撞时标记）"
    )
    duplicate_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        comment="重复发票指向的原始发票ID（自引用）"
    )

    # ── AI 科目建议 ───────────────────────────────────────────────────────────
    suggested_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_categories.id", ondelete="SET NULL"),
        nullable=True,
        comment="A2 Agent 建议的费用科目ID（OCR 识别后自动推荐）"
    )
    confirmed_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_categories.id", ondelete="SET NULL"),
        nullable=True,
        comment="申请人或审批人最终确认的费用科目ID"
    )
    category_confidence: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="AI 科目建议置信度（0-1），供前端展示参考"
    )

    # ── 合规信息 ──────────────────────────────────────────────────────────────
    is_within_period: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True,
        comment="发票日期是否在报销期限内（None=待核查，True/False=已核查结果）"
    )
    compliance_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="合规备注（A3 差标合规 Agent 写入的校验说明）"
    )

    # ── 关系 ──────────────────────────────────────────────────────────────────
    items: Mapped[List["InvoiceItem"]] = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="select",
    )
    application: Mapped[Optional["ExpenseApplication"]] = relationship(  # type: ignore[name-defined]
        "ExpenseApplication",
        foreign_keys=[application_id],
        lazy="select",
    )
    duplicate_of: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        remote_side="Invoice.id",
        foreign_keys=[duplicate_of_id],
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# InvoiceItem — 发票明细行
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceItem(TenantBase):
    """
    发票明细行（货物/服务明细）
    一张发票可包含多条明细行，每行对应一类货物或服务。
    所有金额字段单位为分(fen)。
    """
    __tablename__ = "invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属发票ID"
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="货物或应税劳务/服务名称"
    )
    item_spec: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="规格型号"
    )
    unit: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="计量单位，如「件」「箱」「次」"
    )
    quantity: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(14, 4), nullable=True, comment="数量（支持小数）"
    )
    unit_price: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="含税单价，单位：分(fen)，展示时除以100转元"
    )
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="不含税金额，单位：分(fen)，展示时除以100转元"
    )
    tax_rate: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(5, 4), nullable=True, comment="税率（如0.13表示13%）"
    )
    tax_amount: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="税额，单位：分(fen)，展示时除以100转元"
    )

    # ── 关系 ──────────────────────────────────────────────────────────────────
    invoice: Mapped["Invoice"] = relationship(
        "Invoice", back_populates="items", foreign_keys=[invoice_id]
    )
