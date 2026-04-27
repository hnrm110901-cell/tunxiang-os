"""v336 — 宴会合同管理 (Banquet Contracts)

宴会电子合同 + 变更留痕：
- banquet_contracts: 合同主表(甲乙方/条款/定金/付款计划)
- banquet_contract_amendments: 合同变更记录

Revision: v336_banquet_contracts
"""

from alembic import op

revision = "v336_banquet_contracts"
down_revision = "v335_banquets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_contracts (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            contract_no     VARCHAR(20)     NOT NULL,
            banquet_id      UUID            NOT NULL,
            template_id     UUID,
            party_a_name    VARCHAR(200)    NOT NULL,
            party_a_phone   VARCHAR(20)     NOT NULL,
            party_a_id_no   VARCHAR(30),
            party_a_company VARCHAR(200),
            party_b_name    VARCHAR(200)    NOT NULL,
            party_b_license VARCHAR(50),
            event_date      DATE            NOT NULL,
            event_name      VARCHAR(200),
            venue_name      VARCHAR(100),
            table_count     INT             NOT NULL,
            guest_count     INT             NOT NULL,
            menu_snapshot_json  JSONB       NOT NULL DEFAULT '[]',
            terms_json      JSONB           NOT NULL DEFAULT '{}',
            total_fen       INT             NOT NULL,
            deposit_ratio   NUMERIC(5,2)    NOT NULL DEFAULT 30.00,
            deposit_fen     INT             NOT NULL,
            payment_schedule_json JSONB     NOT NULL DEFAULT '[]',
            signed_at       TIMESTAMPTZ,
            signed_by_customer VARCHAR(100),
            signed_by_staff UUID,
            status          VARCHAR(20)     NOT NULL DEFAULT 'draft',
            amendment_count INT             NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_contracts_pkey PRIMARY KEY (id),
            CONSTRAINT banquet_contracts_no_uq UNIQUE (contract_no),
            CONSTRAINT banquet_contracts_status_chk CHECK (
                status IN ('draft','pending_sign','signed','amended','terminated','completed')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bct_banquet ON banquet_contracts (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bct_status  ON banquet_contracts (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bct_date    ON banquet_contracts (tenant_id, event_date)")
    op.execute("ALTER TABLE banquet_contracts ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_contracts_tenant_isolation ON banquet_contracts")
    op.execute("""
        CREATE POLICY banquet_contracts_tenant_isolation ON banquet_contracts
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_contracts FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_contract_amendments (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            contract_id     UUID            NOT NULL,
            amendment_no    INT             NOT NULL,
            change_type     VARCHAR(30)     NOT NULL,
            old_value_json  JSONB           NOT NULL DEFAULT '{}',
            new_value_json  JSONB           NOT NULL DEFAULT '{}',
            reason          TEXT            NOT NULL,
            price_diff_fen  INT             NOT NULL DEFAULT 0,
            approved_by     UUID,
            approved_at     TIMESTAMPTZ,
            status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_contract_amendments_pkey PRIMARY KEY (id),
            CONSTRAINT bca_change_type_chk CHECK (
                change_type IN ('menu','table_count','guest_count','date','venue','price','terms','other')
            ),
            CONSTRAINT bca_status_chk CHECK (status IN ('pending','approved','rejected'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bca_contract ON banquet_contract_amendments (tenant_id, contract_id)")
    op.execute("ALTER TABLE banquet_contract_amendments ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_contract_amendments_tenant_isolation ON banquet_contract_amendments")
    op.execute("""
        CREATE POLICY banquet_contract_amendments_tenant_isolation ON banquet_contract_amendments
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_contract_amendments FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_contract_amendments CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_contracts CASCADE")
