"""v429 — ingredient_yield_standards（PRD-06 / Phase 2 W7-2 / Tier 1 毛利底线）

业务背景：
  徐记海鲜 100 斤毛菜出 60 斤净菜，出料率（yield_rate）随季节波动（春菠菜
  65% / 夏菠菜 50%）。出料率没标准 → BOM 算成本是假的 → 毛利全假。本表
  为每原料维护**标准出料率**（季节差异），BOM 反算购买量自动除以 yield_rate，
  实际 vs 标准超 ±tolerance_pct 触发 yield_anomaly 事件预警。

设计要点：
  1. ingredient_yield_standards — 出料率标准库主表
     - process_id:      NULL = 通用; NOT NULL = 关联工序
     - yield_rate:      (0, 1] 出料率（净 / 毛）
     - season:          spring/summer/autumn/winter/all（季节差异）
     - tolerance_pct:   实测 vs 标准差 > tolerance_pct → 触发 yield_anomaly
     - effective_from/effective_to: 时效窗口（None = 永久）
     - approved_by/approved_at: 二级审批（NULL = 草稿；NOT NULL = 已审批生效）
  2. RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
  3. inspector-and-skip 模式：已存在时跳过（与 v421/v423/v424/v428 一致）

Revision ID: v429_ingredient_yield_standards
Revises: v428_ingredient_weight_standards
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v429_ingredient_yield_standards"
down_revision: Union[str, Sequence[str], None] = "v428_ingredient_weight_standards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "ingredient_yield_standards" not in existing:
        op.execute(
            """
            CREATE TABLE ingredient_yield_standards (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                process_id          UUID,
                yield_rate          NUMERIC(5,4) NOT NULL,
                season              VARCHAR(10) NOT NULL,
                effective_from      DATE NOT NULL,
                effective_to        DATE,
                tolerance_pct       NUMERIC(5,2) NOT NULL DEFAULT 5.0,
                approved_by         UUID,
                approved_at         TIMESTAMPTZ,
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_iys_yield_rate_range
                    CHECK (yield_rate > 0 AND yield_rate <= 1),
                CONSTRAINT chk_iys_season
                    CHECK (season IN ('spring','summer','autumn','winter','all')),
                CONSTRAINT chk_iys_tolerance_range
                    CHECK (tolerance_pct >= 0 AND tolerance_pct <= 100),
                CONSTRAINT chk_iys_effective_dates
                    CHECK (effective_to IS NULL OR effective_to > effective_from)
            )
            """
        )

        op.execute("ALTER TABLE ingredient_yield_standards ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE ingredient_yield_standards FORCE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY ingredient_yield_standards_tenant_isolation
            ON ingredient_yield_standards
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 主查询路径：按 ingredient 找 standards
        op.execute(
            """
            CREATE INDEX idx_iys_tenant_ingredient
            ON ingredient_yield_standards (tenant_id, ingredient_id)
            """
        )

        # BOM 反算时筛 active 标准的覆盖索引（部分索引压缩存储）
        op.execute(
            """
            CREATE INDEX idx_iys_active
            ON ingredient_yield_standards (tenant_id, ingredient_id, season, effective_from)
            WHERE approved_by IS NOT NULL AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "ingredient_yield_standards" in existing:
        op.execute("DROP TABLE ingredient_yield_standards CASCADE")
