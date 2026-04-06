"""v170 — 顾客意见反馈 + 营销方案

创建：
  customer_suggestions  — 顾客意见/投诉/建议记录
  marketing_schemes     — 营销折扣方案配置

Revision: v170
"""

from alembic import op

revision = "v170"
down_revision = "v169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_suggestions (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID,
            customer_id     UUID,
            category        VARCHAR(32) NOT NULL DEFAULT 'general',
            -- general / complaint / praise / suggestion
            content         TEXT        NOT NULL,
            contact_phone   VARCHAR(32),
            status          VARCHAR(16) NOT NULL DEFAULT 'pending',
            -- pending / processing / resolved / closed
            reply           TEXT,
            replied_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_customer_suggestions_tenant ON customer_suggestions (tenant_id, created_at DESC)")
    op.execute("ALTER TABLE customer_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY customer_suggestions_tenant_isolation ON customer_suggestions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE customer_suggestions FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_schemes (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            name            VARCHAR(128) NOT NULL,
            scheme_type     VARCHAR(32) NOT NULL DEFAULT 'discount',
            -- discount / points_multiplier / gift / bundle
            rules           JSONB       NOT NULL DEFAULT '{}',
            -- {"min_amount_fen": 10000, "discount_rate": 0.9, ...}
            is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
            valid_from      DATE,
            valid_until     DATE,
            priority        INT         NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_marketing_schemes_tenant ON marketing_schemes (tenant_id, is_active, priority DESC)")
    op.execute("ALTER TABLE marketing_schemes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY marketing_schemes_tenant_isolation ON marketing_schemes
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE marketing_schemes FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing_schemes")
    op.execute("DROP TABLE IF EXISTS customer_suggestions")
