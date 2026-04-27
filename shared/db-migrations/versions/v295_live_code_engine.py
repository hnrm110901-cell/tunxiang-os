"""v295 — 活码拉新引擎

私域增长模块A：活码引擎，支持门店LBS/会员/群聊三种活码类型。

四张表：
  1. live_codes — 活码配置（企微活码+欢迎语+自动打标）
  2. live_code_scans — 扫码记录（含LBS坐标+匹配门店）
  3. live_code_channel_stats — 渠道统计（按日/门店/活码聚合）
  4. live_code_store_bindings — 门店绑定（活码↔门店↔群聊映射）

Revision ID: v295_live_code
Revises: v294_mrp_forecast
Create Date: 2026-04-24
"""
from alembic import op

revision = "v295_live_code"
down_revision = "v294_mrp_forecast"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. live_codes ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_codes (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            code_name           VARCHAR(200) NOT NULL,
            code_type           VARCHAR(30) NOT NULL DEFAULT 'member'
                                CHECK (code_type IN ('member', 'group', 'lbs')),
            wecom_config_id     UUID,
            welcome_msg         TEXT,
            welcome_media_url   TEXT,
            target_group_ids    JSONB NOT NULL DEFAULT '[]'::jsonb,
            lbs_radius_meters   INT NOT NULL DEFAULT 3000,
            daily_add_limit     INT NOT NULL DEFAULT 200,
            total_add_limit     INT,
            auto_tag_ids        JSONB NOT NULL DEFAULT '[]'::jsonb,
            channel_source      VARCHAR(100),
            qr_image_url        TEXT,
            status              VARCHAR(20) NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'paused', 'expired')),
            expires_at          TIMESTAMPTZ,
            created_by          UUID NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_codes_tenant_status
            ON live_codes (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_codes_store
            ON live_codes (tenant_id, store_id, created_at DESC)
            WHERE is_deleted = false AND store_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_codes_channel
            ON live_codes (tenant_id, channel_source)
            WHERE is_deleted = false AND channel_source IS NOT NULL
    """)

    op.execute("ALTER TABLE live_codes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS live_codes_tenant_isolation ON live_codes;
        CREATE POLICY live_codes_tenant_isolation ON live_codes
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. live_code_scans ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_code_scans (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            live_code_id            UUID NOT NULL REFERENCES live_codes(id),
            store_id                UUID,
            customer_id             UUID,
            wecom_external_userid   VARCHAR(200),
            scan_source             VARCHAR(50),
            latitude                NUMERIC(10,7),
            longitude               NUMERIC(10,7),
            matched_store_id        UUID,
            result                  VARCHAR(20) NOT NULL DEFAULT 'success'
                                    CHECK (result IN ('success', 'limit_reached', 'expired', 'error')),
            device_info             JSONB,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_code_scans_code
            ON live_code_scans (live_code_id, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_code_scans_tenant
            ON live_code_scans (tenant_id, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_code_scans_customer
            ON live_code_scans (tenant_id, customer_id)
            WHERE is_deleted = false AND customer_id IS NOT NULL
    """)

    op.execute("ALTER TABLE live_code_scans ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS live_code_scans_tenant_isolation ON live_code_scans;
        CREATE POLICY live_code_scans_tenant_isolation ON live_code_scans
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. live_code_channel_stats ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_code_channel_stats (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            live_code_id            UUID NOT NULL REFERENCES live_codes(id),
            store_id                UUID,
            stat_date               DATE NOT NULL,
            scan_count              INT NOT NULL DEFAULT 0,
            success_count           INT NOT NULL DEFAULT 0,
            new_friend_count        INT NOT NULL DEFAULT 0,
            new_group_member_count  INT NOT NULL DEFAULT 0,
            lost_count              INT NOT NULL DEFAULT 0,
            retention_count         INT NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_live_code_channel_stats
                UNIQUE (tenant_id, live_code_id, store_id, stat_date)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lc_channel_stats_date
            ON live_code_channel_stats (tenant_id, stat_date DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE live_code_channel_stats ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS lc_channel_stats_tenant_isolation ON live_code_channel_stats;
        CREATE POLICY lc_channel_stats_tenant_isolation ON live_code_channel_stats
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. live_code_store_bindings ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_code_store_bindings (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            live_code_id        UUID NOT NULL REFERENCES live_codes(id),
            store_id            UUID NOT NULL,
            group_chat_id       VARCHAR(200),
            wecom_userid        VARCHAR(200),
            latitude            NUMERIC(10,7),
            longitude           NUMERIC(10,7),
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_live_code_store_binding
                UNIQUE (tenant_id, live_code_id, store_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lc_store_bindings_code
            ON live_code_store_bindings (live_code_id, is_active)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE live_code_store_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS lc_store_bindings_tenant_isolation ON live_code_store_bindings;
        CREATE POLICY lc_store_bindings_tenant_isolation ON live_code_store_bindings
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS live_code_store_bindings CASCADE")
    op.execute("DROP TABLE IF EXISTS live_code_channel_stats CASCADE")
    op.execute("DROP TABLE IF EXISTS live_code_scans CASCADE")
    op.execute("DROP TABLE IF EXISTS live_codes CASCADE")
