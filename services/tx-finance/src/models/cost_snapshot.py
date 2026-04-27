"""成本快照模型 — 订单成本追溯与毛利率记录

# SCHEMA SQL (由专门迁移agent统一处理，不直接运行):
# CREATE TABLE cost_snapshots (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     order_id UUID NOT NULL,
#     order_item_id UUID NOT NULL,
#     dish_id UUID NOT NULL,
#     raw_material_cost NUMERIC(10,4) NOT NULL DEFAULT 0,
#     labor_cost_allocated NUMERIC(10,4) DEFAULT 0,
#     overhead_allocated NUMERIC(10,4) DEFAULT 0,
#     total_cost NUMERIC(10,4) NOT NULL,
#     selling_price NUMERIC(10,2) NOT NULL,
#     gross_margin_rate NUMERIC(5,4),
#     bom_version_id UUID,
#     computed_at TIMESTAMPTZ DEFAULT NOW(),
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
# CREATE INDEX idx_cost_snapshots_tenant_order ON cost_snapshots(tenant_id, order_id);
# CREATE INDEX idx_cost_snapshots_tenant_dish ON cost_snapshots(tenant_id, dish_id);
# ALTER TABLE cost_snapshots ENABLE ROW LEVEL SECURITY;
# CREATE POLICY cost_snapshots_tenant_isolation ON cost_snapshots
#     USING (tenant_id = current_setting('app.tenant_id')::UUID);
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CostSnapshot(Base):
    """每笔订单明细的成本快照

    - 实时计算后写入，供P&L报表高效查询
    - 支持按订单、门店、日期聚合
    - bom_version_id=None 表示使用了菜品标准成本fallback
    """

    __tablename__ = "cost_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    order_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dish_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # 成本分解
    raw_material_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0, comment="原料成本(分)")
    labor_cost_allocated: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment="分摊人工成本(分)")
    overhead_allocated: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment="分摊管理费用(分)")
    total_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, comment="总成本=原料+人工+管理费(分)")

    # 售价与毛利
    selling_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, comment="实际销售价格(分)")
    gross_margin_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), comment="毛利率=(售价-成本)/售价")

    # BOM追溯
    bom_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="使用的BOM版本ID，NULL=fallback标准成本"
    )
    cost_source: Mapped[str] = mapped_column(
        String(20), default="bom", comment="成本来源: bom | standard_cost | manual"
    )

    # 时间戳
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="成本计算时间"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_cost_snapshots_tenant_order", "tenant_id", "order_id"),
        Index("idx_cost_snapshots_tenant_dish_date", "tenant_id", "dish_id", "computed_at"),
    )
