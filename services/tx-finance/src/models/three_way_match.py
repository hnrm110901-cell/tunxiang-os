"""三单匹配记录模型

# SCHEMA SQL（由迁移脚本创建，此处仅供参考）：
# CREATE TABLE purchase_match_records (
#     id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id       UUID NOT NULL,
#     purchase_order_id UUID NOT NULL,
#     supplier_id     UUID,
#     store_id        UUID,
#     status          VARCHAR(30) NOT NULL DEFAULT 'pending',
#     po_amount_fen   BIGINT NOT NULL DEFAULT 0,
#     recv_amount_fen BIGINT NOT NULL DEFAULT 0,
#     inv_amount_fen  BIGINT,
#     variance_amount_fen BIGINT NOT NULL DEFAULT 0,
#     line_variances  JSONB NOT NULL DEFAULT '[]',
#     suggestion      TEXT,
#     resolved_by     UUID,
#     resolved_at     TIMESTAMPTZ,
#     resolution_note TEXT,
#     matched_at      TIMESTAMPTZ DEFAULT NOW(),
#     created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#     updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#     is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
# );
# CREATE INDEX idx_pmr_tenant_po ON purchase_match_records (tenant_id, purchase_order_id);
# CREATE INDEX idx_pmr_tenant_status ON purchase_match_records (tenant_id, status);
# CREATE INDEX idx_pmr_tenant_supplier ON purchase_match_records (tenant_id, supplier_id);
# ALTER TABLE purchase_match_records ENABLE ROW LEVEL SECURITY;
# ALTER TABLE purchase_match_records FORCE ROW LEVEL SECURITY;
# CREATE POLICY pmr_select ON purchase_match_records FOR SELECT
#     USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID
#            AND current_setting('app.tenant_id', TRUE) IS NOT NULL
#            AND current_setting('app.tenant_id', TRUE) <> '');
# CREATE POLICY pmr_insert ON purchase_match_records FOR INSERT
#     WITH CHECK (tenant_id = current_setting('app.tenant_id', TRUE)::UUID
#                 AND current_setting('app.tenant_id', TRUE) IS NOT NULL
#                 AND current_setting('app.tenant_id', TRUE) <> '');
# CREATE POLICY pmr_update ON purchase_match_records FOR UPDATE
#     USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID
#            AND current_setting('app.tenant_id', TRUE) IS NOT NULL
#            AND current_setting('app.tenant_id', TRUE) <> '');
# CREATE POLICY pmr_delete ON purchase_match_records FOR DELETE
#     USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID
#            AND current_setting('app.tenant_id', TRUE) IS NOT NULL
#            AND current_setting('app.tenant_id', TRUE) <> '');
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ThreeWayMatchRecord(Base):
    """采购三单匹配结果持久化记录

    每次执行匹配后写入一条记录，保留历史对账轨迹。
    对同一采购单多次匹配会更新此记录（upsert）。
    """

    __tablename__ = "purchase_match_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # 匹配状态：matched / quantity_variance / price_variance /
    #           missing_invoice / missing_receiving / multi_variance
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    # 金额（分）
    po_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    recv_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    inv_amount_fen: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    variance_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # 差异明细（JSON 数组，每项一个对象）
    line_variances: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # AI 建议
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 核销信息
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_pmr_tenant_po", "tenant_id", "purchase_order_id"),
        Index("idx_pmr_tenant_status", "tenant_id", "status"),
        Index("idx_pmr_tenant_supplier", "tenant_id", "supplier_id"),
    )
