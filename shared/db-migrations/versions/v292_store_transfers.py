"""v251: store transfer orders + cost allocation tables

借调单管理 + 成本分摊记录持久化。支持跨门店借调工时拆分与薪资成本分摊。

Revision ID: v251
Revises: v250
Create Date: 2026-04-13
"""
from alembic import op

revision = "v292"
down_revision = "v291"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store_transfer_orders — 借调单
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_transfer_orders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            employee_name   VARCHAR(100),
            from_store_id   UUID NOT NULL,
            from_store_name VARCHAR(100),
            to_store_id     UUID NOT NULL,
            to_store_name   VARCHAR(100),
            transfer_type   VARCHAR(20) DEFAULT 'temporary',
            start_date      DATE NOT NULL,
            end_date        DATE,
            status          VARCHAR(20) DEFAULT 'pending',
            reason          TEXT,
            approved_by     UUID,
            approved_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfer_orders_tenant_employee
            ON store_transfer_orders (tenant_id, employee_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfer_orders_tenant_status
            ON store_transfer_orders (tenant_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfer_orders_from_store
            ON store_transfer_orders (tenant_id, from_store_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfer_orders_to_store
            ON store_transfer_orders (tenant_id, to_store_id)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE store_transfer_orders ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY store_transfer_orders_rls ON store_transfer_orders
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # transfer_cost_allocations — 成本分摊记录
    op.execute("""
        CREATE TABLE IF NOT EXISTS transfer_cost_allocations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            transfer_order_id   UUID NOT NULL,
            employee_id         UUID NOT NULL,
            store_id            UUID NOT NULL,
            month               VARCHAR(7) NOT NULL,
            worked_hours        NUMERIC(6,2) DEFAULT 0,
            wage_fen            INT DEFAULT 0,
            social_insurance_fen INT DEFAULT 0,
            bonus_fen           INT DEFAULT 0,
            total_fen           INT DEFAULT 0,
            ratio               NUMERIC(8,6) DEFAULT 0,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_alloc_tenant_employee_month
            ON transfer_cost_allocations (tenant_id, employee_id, month)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_alloc_tenant_store_month
            ON transfer_cost_allocations (tenant_id, store_id, month)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_alloc_transfer_order
            ON transfer_cost_allocations (tenant_id, transfer_order_id)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE transfer_cost_allocations ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY transfer_cost_allocations_rls ON transfer_cost_allocations
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfer_cost_allocations")
    op.execute("DROP TABLE IF EXISTS store_transfer_orders")
