"""v053 — 供应链移动端

新增表：
  receiving_orders  — 收货单
  receiving_items   — 收货明细
  stocktake_sessions — 盘点任务
  stocktake_items   — 盘点明细

RLS 策略：标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v053
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v053"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS receiving_orders (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            purchase_order_id   UUID        DEFAULT NULL,
            supplier_name       VARCHAR(200),
            status              VARCHAR(20) NOT NULL DEFAULT 'draft',
            receiver_id         UUID        DEFAULT NULL,
            received_at         TIMESTAMPTZ DEFAULT NULL,
            notes               TEXT        DEFAULT NULL,
            photo_urls          JSONB       NOT NULL DEFAULT '[]',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_receiving_orders_tenant_store
            ON receiving_orders (tenant_id, store_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_receiving_orders_tenant_created
            ON receiving_orders (tenant_id, created_at DESC)
            WHERE is_deleted = FALSE;

        ALTER TABLE receiving_orders ENABLE ROW LEVEL SECURITY;
        ALTER TABLE receiving_orders FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS receiving_orders_select ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_insert ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_update ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_delete ON receiving_orders;

        CREATE POLICY receiving_orders_select ON receiving_orders
            FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY receiving_orders_insert ON receiving_orders
            FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY receiving_orders_update ON receiving_orders
            FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY receiving_orders_delete ON receiving_orders
            FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS receiving_items (
            id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID          NOT NULL,
            receiving_order_id  UUID          NOT NULL,
            ingredient_id       UUID          DEFAULT NULL,
            ingredient_name     VARCHAR(200)  NOT NULL,
            unit                VARCHAR(20),
            ordered_qty         NUMERIC(10,3) DEFAULT NULL,
            received_qty        NUMERIC(10,3) DEFAULT NULL,
            unit_price          NUMERIC(12,2) DEFAULT NULL,
            discrepancy_note    TEXT          DEFAULT NULL,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_receiving_items_tenant_order
            ON receiving_items (tenant_id, receiving_order_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_sessions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            category        VARCHAR(100) DEFAULT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'in_progress',
            initiated_by    UUID        DEFAULT NULL,
            completed_at    TIMESTAMPTZ DEFAULT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_stocktake_sessions_tenant_store
            ON stocktake_sessions (tenant_id, store_id)
            WHERE is_deleted = FALSE;

        ALTER TABLE stocktake_sessions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE stocktake_sessions FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS stocktake_sessions_select ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_insert ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_update ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_delete ON stocktake_sessions;

        CREATE POLICY stocktake_sessions_select ON stocktake_sessions
            FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY stocktake_sessions_insert ON stocktake_sessions
            FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY stocktake_sessions_update ON stocktake_sessions
            FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY stocktake_sessions_delete ON stocktake_sessions
            FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );
    """)

    op.execute("ALTER TABLE stocktake_items ADD COLUMN IF NOT EXISTS session_id UUID")
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_items (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID          NOT NULL,
            session_id      UUID          NOT NULL,
            ingredient_id   UUID          DEFAULT NULL,
            ingredient_name VARCHAR(200)  NOT NULL,
            unit            VARCHAR(20),
            system_qty      NUMERIC(10,3) DEFAULT NULL,
            actual_qty      NUMERIC(10,3) DEFAULT NULL,
            variance        NUMERIC(10,3) DEFAULT NULL,
            variance_value  NUMERIC(12,2) DEFAULT NULL,
            counted_by      UUID          DEFAULT NULL,
            counted_at      TIMESTAMPTZ   DEFAULT NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_stocktake_items_tenant_session
            ON stocktake_items (tenant_id, session_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS stocktake_sessions_delete ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_update ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_insert ON stocktake_sessions;
        DROP POLICY IF EXISTS stocktake_sessions_select ON stocktake_sessions;

        DROP POLICY IF EXISTS receiving_orders_delete ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_update ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_insert ON receiving_orders;
        DROP POLICY IF EXISTS receiving_orders_select ON receiving_orders;

        DROP TABLE IF EXISTS stocktake_items;
        DROP TABLE IF EXISTS stocktake_sessions;
        DROP TABLE IF EXISTS receiving_items;
        DROP TABLE IF EXISTS receiving_orders;
    """)
