"""v049 — 服务铃呼叫记录

新增表：service_bell_calls

Revision ID: v049
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v049"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS service_bell_calls (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            store_id         UUID         NOT NULL,
            table_no         VARCHAR(20)  NOT NULL,
            call_type        VARCHAR(50)  NOT NULL
                CHECK (call_type IN ('add_dish', 'checkout', 'paper', 'water', 'other')),
            call_type_label  VARCHAR(100),
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'responded', 'ignored')),
            operator_id      UUID,
            called_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            responded_at     TIMESTAMPTZ,
            is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE service_bell_calls IS
            '服务铃呼叫记录：顾客扫桌台码呼叫服务员的实时记录';

        CREATE INDEX IF NOT EXISTS ix_service_bell_tenant_store
            ON service_bell_calls (tenant_id, store_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_service_bell_table_status
            ON service_bell_calls (table_no, status)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_service_bell_called_at
            ON service_bell_calls (called_at DESC);
    """)

    op.execute("""
        ALTER TABLE service_bell_calls ENABLE ROW LEVEL SECURITY;
        ALTER TABLE service_bell_calls FORCE ROW LEVEL SECURITY;

        CREATE POLICY service_bell_calls_tenant_isolation ON service_bell_calls
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS service_bell_calls_tenant_isolation ON service_bell_calls;")
    op.execute("DROP TABLE IF EXISTS service_bell_calls;")
