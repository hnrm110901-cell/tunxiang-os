"""v343 — 宴会结算 (Banquet Settlements)

- banquet_settlements: 结算主单(定金抵扣/加菜/酒水/服务费)
- banquet_settlement_items: 结算明细行

Revision: v343_banquet_settlements
"""

from alembic import op

revision = "v343_banquet_settlements"
down_revision = "v342_banquet_live_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_settlements (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            settlement_no       VARCHAR(20)     NOT NULL,
            banquet_id          UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            contract_amount_fen INT             NOT NULL DEFAULT 0,
            deposit_paid_fen    INT             NOT NULL DEFAULT 0,
            live_order_amount_fen INT           NOT NULL DEFAULT 0,
            service_fee_fen     INT             NOT NULL DEFAULT 0,
            venue_fee_fen       INT             NOT NULL DEFAULT 0,
            decoration_fee_fen  INT             NOT NULL DEFAULT 0,
            other_fee_fen       INT             NOT NULL DEFAULT 0,
            discount_fen        INT             NOT NULL DEFAULT 0,
            subtotal_fen        INT             NOT NULL DEFAULT 0,
            balance_due_fen     INT             NOT NULL DEFAULT 0,
            payment_method      VARCHAR(30),
            payment_ref         VARCHAR(100),
            settled_at          TIMESTAMPTZ,
            settled_by          UUID,
            invoice_status      VARCHAR(20)     NOT NULL DEFAULT 'none',
            invoice_no          VARCHAR(50),
            invoice_amount_fen  INT             NOT NULL DEFAULT 0,
            b2b_client_id       UUID,
            b2b_monthly         BOOLEAN         NOT NULL DEFAULT FALSE,
            notes               TEXT,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_settlements_pkey PRIMARY KEY (id),
            CONSTRAINT banquet_settlements_no_uq UNIQUE (settlement_no),
            CONSTRAINT bs_invoice_chk CHECK (invoice_status IN ('none','requested','issued','cancelled'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bs_banquet ON banquet_settlements (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bs_store   ON banquet_settlements (tenant_id, store_id)")
    op.execute("ALTER TABLE banquet_settlements ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_settlements_tenant_isolation ON banquet_settlements")
    op.execute("""
        CREATE POLICY banquet_settlements_tenant_isolation ON banquet_settlements
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_settlements FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_settlement_items (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            settlement_id   UUID            NOT NULL,
            item_type       VARCHAR(30)     NOT NULL,
            item_name       VARCHAR(200)    NOT NULL,
            quantity        INT             NOT NULL DEFAULT 1,
            unit_price_fen  INT             NOT NULL DEFAULT 0,
            subtotal_fen    INT             NOT NULL DEFAULT 0,
            source          VARCHAR(30)     NOT NULL DEFAULT 'contract',
            source_id       UUID,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_settlement_items_pkey PRIMARY KEY (id),
            CONSTRAINT bsi_type_chk CHECK (item_type IN ('dish','drink','decoration','service','venue','live_add','live_cancel','discount','deposit_offset','other')),
            CONSTRAINT bsi_source_chk CHECK (source IN ('contract','live_order','fee','adjustment'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bsi_settlement ON banquet_settlement_items (tenant_id, settlement_id)")
    op.execute("ALTER TABLE banquet_settlement_items ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_settlement_items_tenant_isolation ON banquet_settlement_items")
    op.execute("""
        CREATE POLICY banquet_settlement_items_tenant_isolation ON banquet_settlement_items
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_settlement_items FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_settlement_items CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_settlements CASCADE")
