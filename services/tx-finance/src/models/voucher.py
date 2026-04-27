"""财务凭证模型 — 会计凭证骨架（销售/成本/收款/付款）

# SCHEMA SQL (由专门迁移agent统一处理，不直接运行):
# CREATE TABLE financial_vouchers (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     store_id UUID NOT NULL,
#     voucher_no VARCHAR(50) UNIQUE NOT NULL,
#     voucher_date DATE NOT NULL,
#     voucher_type VARCHAR(20) NOT NULL, -- sales/cost/payment/receipt
#     total_amount NUMERIC(12,2) NOT NULL,
#     entries JSONB NOT NULL, -- [{account_code, debit, credit, summary}]
#     source_type VARCHAR(30), -- order/settlement/payment
#     source_id UUID,
#     status VARCHAR(20) DEFAULT 'draft', -- draft/confirmed/exported
#     exported_at TIMESTAMPTZ,
#     created_at TIMESTAMPTZ DEFAULT NOW(),
#     updated_at TIMESTAMPTZ DEFAULT NOW()
# );
# CREATE INDEX idx_financial_vouchers_tenant_store_date
#     ON financial_vouchers(tenant_id, store_id, voucher_date);
# CREATE INDEX idx_financial_vouchers_status ON financial_vouchers(tenant_id, status);
# ALTER TABLE financial_vouchers ENABLE ROW LEVEL SECURITY;
# CREATE POLICY financial_vouchers_tenant_isolation ON financial_vouchers
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .cost_snapshot import Base


class FinancialVoucher(Base):
    """财务凭证

    entries JSONB 结构（每条分录）：
    [
        {
            "account_code": "6001",
            "account_name": "主营业务收入-餐饮",
            "debit": 0.00,        # 借方金额（元）
            "credit": 1000.00,    # 贷方金额（元）
            "summary": "2026-03-30堂食收入"
        },
        ...
    ]

    voucher_type 枚举：
    - sales    : 销售收入凭证
    - cost     : 成本结转凭证
    - payment  : 付款凭证
    - receipt  : 收款凭证

    status 枚举：
    - draft     : 草稿（系统自动生成，未审核）
    - confirmed : 已确认（财务审核通过）
    - exported  : 已导出（推送金蝶/用友等ERP）
    """

    __tablename__ = "financial_vouchers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # 凭证标识
    voucher_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="凭证编号，格式: V{store_short}{YYYYMMDD}{SEQ}"
    )
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="凭证日期（业务日期）")
    voucher_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="凭证类型: sales/cost/payment/receipt"
    )

    # 金额
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="凭证总金额（元）")

    # 分录（JSONB）
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, comment="会计分录列表 [{account_code, debit, credit, summary}]"
    )

    # 来源追溯
    source_type: Mapped[str | None] = mapped_column(String(30), comment="来源类型: order/settlement/payment")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="来源单据ID（订单ID/日结ID等）")

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True, comment="状态: draft/confirmed/exported"
    )
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="导出到ERP的时间")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_financial_vouchers_tenant_store_date", "tenant_id", "store_id", "voucher_date"),
        Index("idx_financial_vouchers_status", "tenant_id", "status"),
    )

    def is_balanced(self) -> bool:
        """验证借贷平衡"""
        total_debit = sum(e.get("debit", 0) for e in self.entries)
        total_credit = sum(e.get("credit", 0) for e in self.entries)
        return abs(total_debit - total_credit) < 0.001

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "voucher_no": self.voucher_no,
            "voucher_date": str(self.voucher_date),
            "voucher_type": self.voucher_type,
            "total_amount": float(self.total_amount),
            "entries": self.entries,
            "source_type": self.source_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "status": self.status,
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
            "is_balanced": self.is_balanced(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
