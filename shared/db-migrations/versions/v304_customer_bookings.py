"""v169 — 顾客预约与排队系统

创建：
  customer_bookings   — 桌位/宴席/活动预约
  queue_tickets       — 现场排队取号记录

Revision: v169
"""

from alembic import op

revision = "v304"
down_revision = "v303"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_bookings (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            customer_name   VARCHAR(64) NOT NULL,
            customer_phone  VARCHAR(32) NOT NULL,
            party_size      INT         NOT NULL DEFAULT 1,
            booking_date    DATE        NOT NULL,
            booking_time    VARCHAR(10) NOT NULL,   -- HH:MM
            table_type      VARCHAR(32),
            special_request TEXT,
            status          VARCHAR(16) NOT NULL DEFAULT 'confirmed',
            -- confirmed / arrived / cancelled / no_show
            source          VARCHAR(16) NOT NULL DEFAULT 'walk_in',
            cancelled_at    TIMESTAMPTZ,
            cancel_reason   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_customer_bookings_tenant_date ON customer_bookings (tenant_id, booking_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_customer_bookings_store_date ON customer_bookings (tenant_id, store_id, booking_date)")
    op.execute("ALTER TABLE customer_bookings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY customer_bookings_tenant_isolation ON customer_bookings
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE customer_bookings FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS queue_tickets (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            ticket_no       VARCHAR(16) NOT NULL,   -- A001 / B023 等
            customer_name   VARCHAR(64),
            customer_phone  VARCHAR(32),
            party_size      INT         NOT NULL DEFAULT 1,
            queue_type      VARCHAR(32) NOT NULL DEFAULT 'normal',
            status          VARCHAR(16) NOT NULL DEFAULT 'waiting',
            -- waiting / called / seated / cancelled / expired
            called_at       TIMESTAMPTZ,
            seated_at       TIMESTAMPTZ,
            cancelled_at    TIMESTAMPTZ,
            cancel_reason   TEXT,
            wait_minutes    INT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_queue_tickets_tenant_date ON queue_tickets (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_queue_tickets_store_status ON queue_tickets (tenant_id, store_id, status)")
    op.execute("ALTER TABLE queue_tickets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY queue_tickets_tenant_isolation ON queue_tickets
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE queue_tickets FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS queue_tickets")
    op.execute("DROP TABLE IF EXISTS customer_bookings")
