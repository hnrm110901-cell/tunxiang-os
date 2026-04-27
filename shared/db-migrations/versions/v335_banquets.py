"""v319 — 宴会主单: banquets / banquet_status_logs

宴会核心主表，关联线索、报价、场地、桌组，
完整状态机 draft→confirmed→preparing→ready→in_progress→completed→settled。
状态变更日志表记录每次流转。

Revision ID: v319_banquets
Revises: v318_banquet_table_groups
Create Date: 2026-04-25
"""
from alembic import op

revision = "v335_banquets"
down_revision = "v334_banquet_table_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banquets 宴会主单 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquets (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              UUID NOT NULL,
            banquet_no             VARCHAR(20) NOT NULL UNIQUE,
            lead_id                UUID REFERENCES banquet_leads(id),
            quote_id               UUID REFERENCES banquet_quotes(id),
            store_id               UUID NOT NULL,
            venue_id               UUID REFERENCES banquet_venues(id),
            table_group_id         UUID REFERENCES banquet_table_groups(id),
            event_type             VARCHAR(30) NOT NULL,
            event_name             VARCHAR(200),
            event_date             DATE NOT NULL,
            time_slot              VARCHAR(20) NOT NULL,
            host_name              VARCHAR(100) NOT NULL,
            host_phone             VARCHAR(20) NOT NULL,
            contact_name           VARCHAR(100),
            contact_phone          VARCHAR(20),
            guest_count            INT NOT NULL,
            table_count            INT NOT NULL,
            menu_json              JSONB DEFAULT '[]'::jsonb,
            special_requests       TEXT,
            dietary_restrictions   JSONB DEFAULT '[]'::jsonb,
            decoration_requirements TEXT,
            status                 VARCHAR(20) DEFAULT 'draft'
                CHECK (status IN ('draft','confirmed','preparing','ready','in_progress','completed','cancelled','settled')),
            total_amount_fen       INT DEFAULT 0,
            deposit_amount_fen     INT DEFAULT 0,
            deposit_paid           BOOLEAN DEFAULT FALSE,
            deposit_paid_at        TIMESTAMPTZ,
            deposit_payment_method VARCHAR(20),
            balance_fen            INT DEFAULT 0,
            confirmed_at           TIMESTAMPTZ,
            confirmed_by           UUID,
            cancelled_at           TIMESTAMPTZ,
            cancel_reason          VARCHAR(500),
            completed_at           TIMESTAMPTZ,
            settled_at             TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted             BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_b_tenant_store
            ON banquets(tenant_id, store_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_b_event_date
            ON banquets(tenant_id, event_date)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_b_status
            ON banquets(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_b_lead
            ON banquets(tenant_id, lead_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquets_tenant_isolation ON banquets;
        CREATE POLICY banquets_tenant_isolation ON banquets
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquets FORCE ROW LEVEL SECURITY")

    # ── banquet_status_logs 状态变更日志 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_status_logs (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL,
            banquet_id     UUID NOT NULL REFERENCES banquets(id),
            from_status    VARCHAR(20),
            to_status      VARCHAR(20) NOT NULL,
            operator_id    UUID,
            operator_name  VARCHAR(100),
            reason         VARCHAR(500),
            metadata_json  JSONB DEFAULT '{}'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted     BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bsl_banquet
            ON banquet_status_logs(tenant_id, banquet_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_status_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_status_logs_tenant_isolation ON banquet_status_logs;
        CREATE POLICY banquet_status_logs_tenant_isolation ON banquet_status_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_status_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_status_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS banquets CASCADE")
