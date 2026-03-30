"""发票模型 — Invoice

# SCHEMA SQL:
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    order_id UUID NOT NULL,
    invoice_type VARCHAR(20) NOT NULL,  -- vat_special/vat_normal/electronic
    invoice_title VARCHAR(100),
    tax_number VARCHAR(50),
    amount NUMERIC(10,2) NOT NULL,
    tax_amount NUMERIC(10,2),
    invoice_no VARCHAR(50),
    invoice_code VARCHAR(20),
    platform VARCHAR(20) DEFAULT 'nuonuo',
    platform_request_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',  -- pending/issued/failed/cancelled
    pdf_url TEXT,
    issued_at TIMESTAMPTZ,
    failed_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS 策略（迁移中手动添加）：
-- ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY invoices_tenant_isolation ON invoices
--     USING (tenant_id = current_setting('app.tenant_id')::uuid);
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from .cost_snapshot import Base


class Invoice(Base):
    """invoices 表 ORM 映射"""

    __tablename__ = "invoices"

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False, index=True)
    order_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False, index=True)

    # 发票类型：vat_special（增值税专票）/ vat_normal（增值税普票）/ electronic（电子普票）
    invoice_type: str = Column(String(20), nullable=False)
    invoice_title: Optional[str] = Column(String(100))
    tax_number: Optional[str] = Column(String(50))

    amount: Decimal = Column(Numeric(10, 2), nullable=False)
    tax_amount: Optional[Decimal] = Column(Numeric(10, 2))

    # 诺诺返回的发票号码 / 发票代码
    invoice_no: Optional[str] = Column(String(50))
    invoice_code: Optional[str] = Column(String(20))

    # 平台标识（扩展用，默认 nuonuo）
    platform: str = Column(String(20), default="nuonuo", nullable=False)
    # 申请时写入的平台侧请求单号，用于查询回调
    platform_request_id: Optional[str] = Column(String(100), unique=True)

    # 状态流转：pending → issued | failed → (retry) → issued | cancelled
    status: str = Column(String(20), default="pending", nullable=False, index=True)

    pdf_url: Optional[str] = Column(Text)
    issued_at: Optional[datetime] = Column(DateTime(timezone=True))
    failed_reason: Optional[str] = Column(Text)

    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} order_id={self.order_id} "
            f"status={self.status} amount={self.amount}>"
        )
