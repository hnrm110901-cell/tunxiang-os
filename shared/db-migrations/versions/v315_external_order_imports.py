"""v315 — 外部订单导入表: external_order_imports

导入美团/饿了么/大众点评/抖音/小红书等第三方平台订单，
用于CDP多源数据融合与身份匹配。

Revision ID: v315_external_order_imports
Revises: v314_wifi_visit_logs
Create Date: 2026-04-25
"""
from alembic import op

revision = "v315_external_order_imports"
down_revision = "v314_wifi_visit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS external_order_imports (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            source              VARCHAR(30) NOT NULL
                                CHECK (source IN (
                                    'meituan', 'eleme', 'dianping', 'douyin', 'xiaohongshu'
                                )),
            external_order_id   VARCHAR(100) NOT NULL,
            store_id            UUID NOT NULL,
            customer_phone_hash VARCHAR(64),
            matched_customer_id UUID,
            match_confidence    FLOAT DEFAULT 0,
            order_total_fen     BIGINT DEFAULT 0,
            items               JSONB DEFAULT '[]',
            item_count          INT DEFAULT 0,
            rating              FLOAT,
            review_text         TEXT,
            ordered_at          TIMESTAMPTZ NOT NULL,
            imported_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_order_source_dedup
            ON external_order_imports(tenant_id, source, external_order_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ext_order_store_time
            ON external_order_imports(tenant_id, store_id, ordered_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ext_order_matched
            ON external_order_imports(tenant_id, matched_customer_id)
            WHERE is_deleted = false AND matched_customer_id IS NOT NULL
    """)

    op.execute("ALTER TABLE external_order_imports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS external_order_imports_tenant_isolation ON external_order_imports;
        CREATE POLICY external_order_imports_tenant_isolation ON external_order_imports
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE external_order_imports FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS external_order_imports CASCADE")
