"""v316 — 宴会报价模块: banquet_menu_templates / banquet_quotes / banquet_quote_items

套餐模板管理、报价单生成、报价明细行。
金额全部为整数分（fen），支持多版本报价和状态流转。

Revision ID: v316_banquet_quotes
Revises: v315_banquet_leads
Create Date: 2026-04-25
"""
from alembic import op

revision = "v332_banquet_quotes"
down_revision = "v331_banquet_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banquet_menu_templates 套餐模板 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_menu_templates (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL,
            store_id             UUID,
            name                 VARCHAR(100) NOT NULL,
            event_type           VARCHAR(30) NOT NULL,
            tier                 VARCHAR(20) NOT NULL
                CHECK (tier IN ('economy','standard','premium','luxury','custom')),
            per_table_price_fen  INT NOT NULL,
            dish_count           INT DEFAULT 0,
            dishes_json          JSONB DEFAULT '[]'::jsonb,
            cold_dish_count      INT DEFAULT 0,
            hot_dish_count       INT DEFAULT 0,
            staple_count         INT DEFAULT 0,
            dessert_count        INT DEFAULT 0,
            min_tables           INT DEFAULT 1,
            max_tables           INT DEFAULT 100,
            includes_drinks      BOOLEAN DEFAULT FALSE,
            includes_decoration  BOOLEAN DEFAULT FALSE,
            includes_service_fee BOOLEAN DEFAULT FALSE,
            service_fee_rate     NUMERIC(5,2) DEFAULT 0,
            is_customizable      BOOLEAN DEFAULT TRUE,
            sort_order           INT DEFAULT 0,
            is_active            BOOLEAN DEFAULT TRUE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted           BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bmt_tenant_type
            ON banquet_menu_templates(tenant_id, event_type)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bmt_tier
            ON banquet_menu_templates(tenant_id, tier)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_menu_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_menu_templates_tenant_isolation ON banquet_menu_templates;
        CREATE POLICY banquet_menu_templates_tenant_isolation ON banquet_menu_templates
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_menu_templates FORCE ROW LEVEL SECURITY")

    # ── banquet_quotes 报价单 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_quotes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            quote_no        VARCHAR(20) NOT NULL UNIQUE,
            lead_id         UUID NOT NULL REFERENCES banquet_leads(id),
            template_id     UUID REFERENCES banquet_menu_templates(id),
            event_type      VARCHAR(30) NOT NULL,
            table_count     INT NOT NULL,
            guest_count     INT NOT NULL,
            menu_json       JSONB DEFAULT '[]'::jsonb,
            venue_fee_fen   INT DEFAULT 0,
            decoration_fee_fen INT DEFAULT 0,
            service_fee_fen INT DEFAULT 0,
            drink_fee_fen   INT DEFAULT 0,
            other_fee_fen   INT DEFAULT 0,
            subtotal_fen    INT DEFAULT 0,
            discount_fen    INT DEFAULT 0,
            final_fen       INT DEFAULT 0,
            valid_until     DATE,
            status          VARCHAR(20) DEFAULT 'draft'
                CHECK (status IN ('draft','sent','accepted','expired','rejected','superseded')),
            version         INT DEFAULT 1,
            notes           TEXT,
            created_by      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bq_tenant_lead
            ON banquet_quotes(tenant_id, lead_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bq_status
            ON banquet_quotes(tenant_id, status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_quotes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_quotes_tenant_isolation ON banquet_quotes;
        CREATE POLICY banquet_quotes_tenant_isolation ON banquet_quotes
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_quotes FORCE ROW LEVEL SECURITY")

    # ── banquet_quote_items 报价明细行 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_quote_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            quote_id        UUID NOT NULL REFERENCES banquet_quotes(id),
            item_type       VARCHAR(20) NOT NULL
                CHECK (item_type IN ('dish','drink','decoration','service','venue','other')),
            product_id      UUID,
            name            VARCHAR(200) NOT NULL,
            quantity        INT DEFAULT 1,
            unit            VARCHAR(20) DEFAULT '份',
            unit_price_fen  INT NOT NULL,
            subtotal_fen    INT NOT NULL,
            course_order    INT DEFAULT 0,
            note            VARCHAR(500),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bqi_quote
            ON banquet_quote_items(tenant_id, quote_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_quote_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_quote_items_tenant_isolation ON banquet_quote_items;
        CREATE POLICY banquet_quote_items_tenant_isolation ON banquet_quote_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_quote_items FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_quote_items CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_quotes CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_menu_templates CASCADE")
