"""v428 — ingredient_weight_standards + receiving_weight_deductions（PRD-02 / Phase 2 W7 / Tier 1 毛利底线）

业务背景：
  徐记海鲜每天收 30 吨海鲜+蔬菜，毛重报价/送达，按净重用料。扣秤标准不统一
  导致毛利偏差 3~8%。本表为每 SKU 维护标准扣秤项（冰块 8% / 塑料袋 0.3 斤 /
  菜叶损耗 12%）→ 收货时自动扣秤 → 超过 standard ±tolerance_pct 报警。

设计要点：
  1. ingredient_weight_standards — 标准库主表
     - deduct_type:    ice / packaging / leaves / stem / other（扣秤项类目）
     - deduct_method:  percentage（按毛重百分比扣）/ fixed_kg（按固定 kg 扣）
     - tolerance_pct:  实测 vs 标准差 > tolerance_pct → 触发 weight_deduction_anomaly
     - effective_from/effective_to: 时效窗口（None = 永久）
     - approved_by/approved_at: 二级审批（NULL = 草稿；NOT NULL = 已审批生效）
  2. receiving_weight_deductions — 收货扣秤明细日志（ontology 冻结，不动 ReceivingOrderItem）
     - 关联 receiving_order_items.id 记录每次收货应用的扣秤明细
     - gross_weight_kg / net_weight_kg / deductions JSONB（按 standard 应用的列表）
  3. RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
  4. inspector-and-skip 模式：已存在时跳过（与 v421/v423/v424 一致）

Revision ID: v428_ingredient_weight_standards
Revises: v424_supplier_portal_messages
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v428_ingredient_weight_standards"
down_revision: Union[str, Sequence[str], None] = "v424_supplier_portal_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "ingredient_weight_standards" not in existing:
        op.execute(
            """
            CREATE TABLE ingredient_weight_standards (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                deduct_type         VARCHAR(20) NOT NULL,
                deduct_method       VARCHAR(20) NOT NULL,
                deduct_value        NUMERIC(10,4) NOT NULL,
                tolerance_pct       NUMERIC(5,2) NOT NULL DEFAULT 2.0,
                effective_from      DATE NOT NULL,
                effective_to        DATE,
                approved_by         UUID,
                approved_at         TIMESTAMPTZ,
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_iws_deduct_type
                    CHECK (deduct_type IN ('ice','packaging','leaves','stem','other')),
                CONSTRAINT chk_iws_deduct_method
                    CHECK (deduct_method IN ('percentage','fixed_kg')),
                CONSTRAINT chk_iws_deduct_value_nonneg
                    CHECK (deduct_value >= 0),
                CONSTRAINT chk_iws_tolerance_range
                    CHECK (tolerance_pct >= 0 AND tolerance_pct <= 100),
                CONSTRAINT chk_iws_effective_dates
                    CHECK (effective_to IS NULL OR effective_to > effective_from)
            )
            """
        )

        op.execute("ALTER TABLE ingredient_weight_standards ENABLE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY ingredient_weight_standards_tenant_isolation
            ON ingredient_weight_standards
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 主查询路径：按 ingredient 找 active standards
        op.execute(
            """
            CREATE INDEX idx_iws_tenant_ingredient
            ON ingredient_weight_standards (tenant_id, ingredient_id)
            """
        )

        # 收货时筛 active 标准的覆盖索引（部分索引压缩存储）
        op.execute(
            """
            CREATE INDEX idx_iws_active
            ON ingredient_weight_standards (tenant_id, ingredient_id, deduct_type, effective_from)
            WHERE approved_by IS NOT NULL AND is_deleted = FALSE
            """
        )

    if "receiving_weight_deductions" not in existing:
        op.execute(
            """
            CREATE TABLE receiving_weight_deductions (
                id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id                   UUID NOT NULL,
                receiving_order_id          UUID NOT NULL,
                receiving_order_item_id     UUID NOT NULL,
                ingredient_id               UUID NOT NULL,
                gross_weight_kg             NUMERIC(12,4) NOT NULL,
                net_weight_kg               NUMERIC(12,4) NOT NULL,
                deductions                  JSONB NOT NULL DEFAULT '[]'::jsonb,
                anomaly_detected            BOOLEAN NOT NULL DEFAULT FALSE,
                created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_rwd_weight_nonneg
                    CHECK (gross_weight_kg >= 0 AND net_weight_kg >= 0),
                CONSTRAINT chk_rwd_net_le_gross
                    CHECK (net_weight_kg <= gross_weight_kg)
            )
            """
        )

        op.execute("ALTER TABLE receiving_weight_deductions ENABLE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY receiving_weight_deductions_tenant_isolation
            ON receiving_weight_deductions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 反查路径：按收货单 / 明细行查扣秤记录
        op.execute(
            """
            CREATE INDEX idx_rwd_order_item
            ON receiving_weight_deductions (tenant_id, receiving_order_item_id)
            """
        )

        op.execute(
            """
            CREATE INDEX idx_rwd_order
            ON receiving_weight_deductions (tenant_id, receiving_order_id, created_at DESC)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "receiving_weight_deductions" in existing:
        op.execute("DROP TABLE receiving_weight_deductions CASCADE")
    if "ingredient_weight_standards" in existing:
        op.execute("DROP TABLE ingredient_weight_standards CASCADE")
