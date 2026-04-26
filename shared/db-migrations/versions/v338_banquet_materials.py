"""v338 — 宴会原料分解 (Banquet Materials)

BOM分解 + 宴会采购单：
- banquet_material_requirements: 原料需求(库存/采购来源)
- banquet_purchase_orders: 宴会专用采购单(对接tx-supply)

Revision: v338_banquet_materials
"""

from alembic import op

revision = "v338_banquet_materials"
down_revision = "v337_banquet_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_material_requirements (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            banquet_id          UUID            NOT NULL,
            plan_id             UUID,
            ingredient_id       UUID,
            ingredient_name     VARCHAR(100)    NOT NULL,
            category            VARCHAR(50),
            required_qty        NUMERIC(10,2)   NOT NULL,
            unit                VARCHAR(20)     NOT NULL,
            unit_cost_fen       INT             NOT NULL DEFAULT 0,
            total_cost_fen      INT             NOT NULL DEFAULT 0,
            source              VARCHAR(20)     NOT NULL DEFAULT 'purchase',
            inventory_available NUMERIC(10,2)   NOT NULL DEFAULT 0,
            inventory_reserved  NUMERIC(10,2)   NOT NULL DEFAULT 0,
            purchase_needed     NUMERIC(10,2)   NOT NULL DEFAULT 0,
            purchase_order_id   UUID,
            status              VARCHAR(20)     NOT NULL DEFAULT 'calculated',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_material_requirements_pkey PRIMARY KEY (id),
            CONSTRAINT bmr_source_chk CHECK (source IN ('inventory','purchase','both')),
            CONSTRAINT bmr_status_chk CHECK (
                status IN ('calculated','reserved','ordered','received','fulfilled','cancelled')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bmr_banquet    ON banquet_material_requirements (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bmr_status     ON banquet_material_requirements (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bmr_ingredient ON banquet_material_requirements (tenant_id, ingredient_id)")
    op.execute("ALTER TABLE banquet_material_requirements ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_material_requirements_tenant_isolation ON banquet_material_requirements")
    op.execute("""
        CREATE POLICY banquet_material_requirements_tenant_isolation ON banquet_material_requirements
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_material_requirements FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_purchase_orders (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            po_no                   VARCHAR(20)     NOT NULL,
            banquet_id              UUID            NOT NULL,
            store_id                UUID            NOT NULL,
            supplier_id             UUID,
            supplier_name           VARCHAR(200),
            items_json              JSONB           NOT NULL DEFAULT '[]',
            total_fen               INT             NOT NULL DEFAULT 0,
            required_by             DATE            NOT NULL,
            status                  VARCHAR(20)     NOT NULL DEFAULT 'draft',
            linked_supply_order_id  UUID,
            submitted_at            TIMESTAMPTZ,
            received_at             TIMESTAMPTZ,
            notes                   TEXT,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_purchase_orders_pkey PRIMARY KEY (id),
            CONSTRAINT banquet_purchase_orders_no_uq UNIQUE (po_no),
            CONSTRAINT bpo_status_chk CHECK (
                status IN ('draft','submitted','confirmed','partial_received','received','cancelled')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpo_banquet ON banquet_purchase_orders (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpo_status  ON banquet_purchase_orders (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpo_date    ON banquet_purchase_orders (tenant_id, required_by)")
    op.execute("ALTER TABLE banquet_purchase_orders ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_purchase_orders_tenant_isolation ON banquet_purchase_orders")
    op.execute("""
        CREATE POLICY banquet_purchase_orders_tenant_isolation ON banquet_purchase_orders
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_purchase_orders FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_purchase_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_material_requirements CASCADE")
