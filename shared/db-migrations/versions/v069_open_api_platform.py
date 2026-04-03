"""v069 — 开放API平台基础表

Revision ID: v069
Revises: v068
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v069"
down_revision = "v068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── api_applications — ISV应用注册 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_applications (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            app_name            VARCHAR(100) NOT NULL,
            app_key             VARCHAR(64)  NOT NULL,
            app_secret_hash     VARCHAR(128) NOT NULL,
            description         TEXT,
            status              VARCHAR(20)  NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'suspended', 'revoked')),
            scopes              JSONB        NOT NULL DEFAULT '[]',
            rate_limit_per_min  INTEGER      NOT NULL DEFAULT 60,
            webhook_url         VARCHAR(500),
            contact_email       VARCHAR(100),
            created_by          UUID,
            last_active_at      TIMESTAMPTZ,
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE api_applications IS 'ISV应用注册表，存储开放平台接入应用信息';
        COMMENT ON COLUMN api_applications.app_key IS '生成的appKey，用于OAuth2认证，全局唯一';
        COMMENT ON COLUMN api_applications.app_secret_hash IS 'PBKDF2-SHA256哈希，禁止存储明文secret';
        COMMENT ON COLUMN api_applications.scopes IS '允许的权限范围列表，JSONB数组';
        COMMENT ON COLUMN api_applications.rate_limit_per_min IS '每分钟请求数限制，默认60';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_api_apps_app_key
            ON api_applications (app_key);

        CREATE INDEX IF NOT EXISTS idx_api_apps_tenant_status
            ON api_applications (tenant_id, status)
            WHERE is_deleted = FALSE;
    """)

    op.execute("""
        ALTER TABLE api_applications ENABLE ROW LEVEL SECURITY;
        ALTER TABLE api_applications FORCE ROW LEVEL SECURITY;

        CREATE POLICY api_apps_select ON api_applications FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_apps_insert ON api_applications FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_apps_update ON api_applications FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_apps_delete ON api_applications FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
    """)

    # ── api_access_tokens — OAuth2 access token ───────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_access_tokens (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            app_id          UUID        REFERENCES api_applications(id) ON DELETE CASCADE,
            token_hash      VARCHAR(128) NOT NULL,
            token_prefix    VARCHAR(16)  NOT NULL,
            scopes          JSONB        NOT NULL DEFAULT '[]',
            expires_at      TIMESTAMPTZ  NOT NULL,
            revoked_at      TIMESTAMPTZ,
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE api_access_tokens IS 'OAuth2 access token存储表，禁止存储明文token';
        COMMENT ON COLUMN api_access_tokens.token_hash IS 'PBKDF2-SHA256哈希，禁止存储明文token';
        COMMENT ON COLUMN api_access_tokens.token_prefix IS '用于日志展示的token前缀，如txat_abc123...';
        COMMENT ON COLUMN api_access_tokens.expires_at IS 'token过期时间，默认24小时';
        COMMENT ON COLUMN api_access_tokens.revoked_at IS '主动吊销时间，非NULL表示已吊销';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_api_tokens_hash
            ON api_access_tokens (token_hash);

        CREATE INDEX IF NOT EXISTS idx_api_tokens_app_expires
            ON api_access_tokens (app_id, expires_at)
            WHERE revoked_at IS NULL AND is_deleted = FALSE;
    """)

    op.execute("""
        ALTER TABLE api_access_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE api_access_tokens FORCE ROW LEVEL SECURITY;

        CREATE POLICY api_tokens_select ON api_access_tokens FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_tokens_insert ON api_access_tokens FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_tokens_update ON api_access_tokens FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_tokens_delete ON api_access_tokens FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
    """)

    # ── api_request_logs — 请求审计日志（只读，无updated_at/is_deleted）──
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_request_logs (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            app_id              UUID,
            token_id            UUID,
            endpoint            VARCHAR(200),
            method              VARCHAR(10),
            status_code         INTEGER,
            request_duration_ms INTEGER,
            ip_address          VARCHAR(45),
            user_agent          VARCHAR(200),
            request_id          VARCHAR(64),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE api_request_logs IS '开放API请求审计日志，只读，不含金额等敏感字段';
        COMMENT ON COLUMN api_request_logs.request_id IS '幂等key，用于去重';
        COMMENT ON COLUMN api_request_logs.ip_address IS '支持IPv4和IPv6，最长45字符';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_api_logs_request_id
            ON api_request_logs (request_id)
            WHERE request_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_api_logs_tenant_created
            ON api_request_logs (tenant_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_api_logs_app_created
            ON api_request_logs (app_id, created_at);
    """)

    op.execute("""
        ALTER TABLE api_request_logs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE api_request_logs FORCE ROW LEVEL SECURITY;

        CREATE POLICY api_logs_select ON api_request_logs FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_logs_insert ON api_request_logs FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_logs_update ON api_request_logs FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_logs_delete ON api_request_logs FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
    """)

    # ── api_webhooks — Webhook配置 ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_webhooks (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            app_id              UUID        REFERENCES api_applications(id) ON DELETE CASCADE,
            event_types         JSONB        NOT NULL DEFAULT '[]',
            endpoint_url        VARCHAR(500) NOT NULL,
            secret_hash         VARCHAR(128) NOT NULL,
            is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
            retry_count         INTEGER      NOT NULL DEFAULT 3,
            last_triggered_at   TIMESTAMPTZ,
            last_status         VARCHAR(20),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE api_webhooks IS 'Webhook配置表，存储ISV订阅的事件推送端点';
        COMMENT ON COLUMN api_webhooks.event_types IS '订阅的事件类型列表，JSONB数组，如["order.completed","member.registered"]';
        COMMENT ON COLUMN api_webhooks.secret_hash IS 'HMAC签名密钥哈希，用于X-TunXiang-Signature验证';
        COMMENT ON COLUMN api_webhooks.retry_count IS '推送失败最大重试次数，默认3次';

        CREATE INDEX IF NOT EXISTS idx_api_webhooks_tenant_active
            ON api_webhooks (tenant_id, is_active)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_api_webhooks_app
            ON api_webhooks (app_id)
            WHERE is_deleted = FALSE;
    """)

    op.execute("""
        ALTER TABLE api_webhooks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE api_webhooks FORCE ROW LEVEL SECURITY;

        CREATE POLICY api_webhooks_select ON api_webhooks FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_webhooks_insert ON api_webhooks FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_webhooks_update ON api_webhooks FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        CREATE POLICY api_webhooks_delete ON api_webhooks FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
    """)


def downgrade() -> None:
    # 按依赖顺序逆向删除
    for policy in ["api_webhooks_select", "api_webhooks_insert", "api_webhooks_update", "api_webhooks_delete"]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON api_webhooks")
    op.execute("DROP TABLE IF EXISTS api_webhooks")

    for policy in ["api_logs_select", "api_logs_insert", "api_logs_update", "api_logs_delete"]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON api_request_logs")
    op.execute("DROP TABLE IF EXISTS api_request_logs")

    for policy in ["api_tokens_select", "api_tokens_insert", "api_tokens_update", "api_tokens_delete"]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON api_access_tokens")
    op.execute("DROP TABLE IF EXISTS api_access_tokens")

    for policy in ["api_apps_select", "api_apps_insert", "api_apps_update", "api_apps_delete"]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON api_applications")
    op.execute("DROP TABLE IF EXISTS api_applications")
