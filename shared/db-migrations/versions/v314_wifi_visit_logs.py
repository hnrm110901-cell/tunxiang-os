"""v314 — WiFi探针访客日志表: wifi_visit_logs

记录门店WiFi探针采集的访客MAC地址（SHA256哈希）、设备厂商、
访问时段、信号强度，以及身份匹配结果。
支持CDP多源数据融合的WiFi触点。

Revision ID: v314_wifi_visit_logs
Revises: v313_upsell_prompts
Create Date: 2026-04-25
"""
from alembic import op

revision = "v314_wifi_visit_logs"
down_revision = "v313_upsell_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wifi_visit_logs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            mac_hash            VARCHAR(64) NOT NULL,
            device_vendor       VARCHAR(50),
            first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            visit_duration_sec  INT DEFAULT 0,
            signal_strength     INT,
            matched_customer_id UUID,
            match_confidence    FLOAT,
            match_method        VARCHAR(30),
            is_new_visitor      BOOLEAN DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wifi_visit_store_time
            ON wifi_visit_logs(tenant_id, store_id, first_seen_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wifi_visit_mac
            ON wifi_visit_logs(tenant_id, mac_hash)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wifi_visit_matched
            ON wifi_visit_logs(tenant_id, matched_customer_id)
            WHERE is_deleted = false AND matched_customer_id IS NOT NULL
    """)

    op.execute("ALTER TABLE wifi_visit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS wifi_visit_logs_tenant_isolation ON wifi_visit_logs;
        CREATE POLICY wifi_visit_logs_tenant_isolation ON wifi_visit_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE wifi_visit_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wifi_visit_logs CASCADE")
