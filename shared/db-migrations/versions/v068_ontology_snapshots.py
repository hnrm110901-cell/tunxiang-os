"""v068 — Ontology快照表

新增表：
  ontology_snapshots — 6大实体周期性聚合快照，支持集团/品牌/门店三粒度

RLS 策略：标准安全模式（NULLIF + FORCE ROW LEVEL SECURITY）
金额单位：分（fen）

Revision ID: v068
Revises: v067
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v068"
down_revision = "v067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_snapshots (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            brand_id        UUID        DEFAULT NULL,
            store_id        UUID        DEFAULT NULL,
            snapshot_date   DATE        NOT NULL,
            snapshot_type   VARCHAR(20) NOT NULL
                                CHECK (snapshot_type IN ('daily', 'weekly', 'monthly')),
            entity_type     VARCHAR(30) NOT NULL
                                CHECK (entity_type IN ('customer', 'dish', 'store', 'order', 'ingredient', 'employee')),
            metrics         JSONB       NOT NULL DEFAULT '{}',
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );

        COMMENT ON TABLE ontology_snapshots IS '6大实体周期性聚合快照，支持集团/品牌/门店三粒度历史对比';
        COMMENT ON COLUMN ontology_snapshots.brand_id IS 'NULL=集团级快照';
        COMMENT ON COLUMN ontology_snapshots.store_id IS 'NULL=品牌或集团级快照';
        COMMENT ON COLUMN ontology_snapshots.snapshot_type IS 'daily/weekly/monthly';
        COMMENT ON COLUMN ontology_snapshots.entity_type IS 'customer/dish/store/order/ingredient/employee';
        COMMENT ON COLUMN ontology_snapshots.metrics IS '各实体聚合指标 JSONB，金额单位分(fen)';

        CREATE INDEX IF NOT EXISTS idx_onto_snap_tenant_date
            ON ontology_snapshots (tenant_id, snapshot_date);

        CREATE INDEX IF NOT EXISTS idx_onto_snap_brand_entity
            ON ontology_snapshots (brand_id, entity_type, snapshot_date);

        CREATE INDEX IF NOT EXISTS idx_onto_snap_store_entity
            ON ontology_snapshots (store_id, entity_type, snapshot_date);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_onto_snap_lookup
            ON ontology_snapshots (tenant_id, brand_id, store_id, snapshot_type, entity_type, snapshot_date);
    """)

    op.execute("""
        ALTER TABLE ontology_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ontology_snapshots FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS onto_snap_select ON ontology_snapshots;
        CREATE POLICY onto_snap_select ON ontology_snapshots FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        DROP POLICY IF EXISTS onto_snap_insert ON ontology_snapshots;
        CREATE POLICY onto_snap_insert ON ontology_snapshots FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        DROP POLICY IF EXISTS onto_snap_update ON ontology_snapshots;
        CREATE POLICY onto_snap_update ON ontology_snapshots FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        DROP POLICY IF EXISTS onto_snap_delete ON ontology_snapshots;
        CREATE POLICY onto_snap_delete ON ontology_snapshots FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
    """)


def downgrade() -> None:
    for policy in ["onto_snap_select", "onto_snap_insert", "onto_snap_update", "onto_snap_delete"]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON ontology_snapshots")
    op.execute("DROP TABLE IF EXISTS ontology_snapshots")
