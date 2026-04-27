"""v342 — 宴会现场管理 (Live Orders + Guest Check-in)

- banquet_live_orders: 现场加菜/加酒水/特殊需求
- banquet_guest_check_ins: 宾客签到

Revision: v342_banquet_live_orders
"""

from alembic import op

revision = "v342_banquet_live_orders"
down_revision = "v341_banquet_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_live_orders (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            banquet_id      UUID            NOT NULL,
            order_type      VARCHAR(30)     NOT NULL,
            items_json      JSONB           NOT NULL DEFAULT '[]',
            amount_fen      INT             NOT NULL DEFAULT 0,
            quantity         INT             NOT NULL DEFAULT 1,
            requested_by    UUID,
            requested_name  VARCHAR(100),
            approved_by     UUID,
            approved_at     TIMESTAMPTZ,
            reject_reason   VARCHAR(500),
            status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
            fulfilled_at    TIMESTAMPTZ,
            notes           TEXT,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_live_orders_pkey PRIMARY KEY (id),
            CONSTRAINT blo_type_chk CHECK (order_type IN ('add_dish','add_drink','special_request','cancel_dish','upgrade_dish','extra_service')),
            CONSTRAINT blo_status_chk CHECK (status IN ('pending','approved','rejected','fulfilled','cancelled'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_blo_banquet ON banquet_live_orders (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_blo_status  ON banquet_live_orders (tenant_id, status)")
    op.execute("ALTER TABLE banquet_live_orders ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_live_orders_tenant_isolation ON banquet_live_orders")
    op.execute("""
        CREATE POLICY banquet_live_orders_tenant_isolation ON banquet_live_orders
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_live_orders FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_guest_check_ins (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            banquet_id      UUID            NOT NULL,
            table_no        VARCHAR(20),
            guest_name      VARCHAR(100),
            guest_phone     VARCHAR(20),
            check_in_time   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            vip_flag        BOOLEAN         NOT NULL DEFAULT FALSE,
            dietary_notes   VARCHAR(500),
            seat_assignment VARCHAR(50),
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_guest_check_ins_pkey PRIMARY KEY (id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bgci_banquet ON banquet_guest_check_ins (tenant_id, banquet_id)")
    op.execute("ALTER TABLE banquet_guest_check_ins ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_guest_check_ins_tenant_isolation ON banquet_guest_check_ins")
    op.execute("""
        CREATE POLICY banquet_guest_check_ins_tenant_isolation ON banquet_guest_check_ins
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_guest_check_ins FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_guest_check_ins CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_live_orders CASCADE")
