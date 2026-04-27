"""v321 — AI引用监测表: ai_citation_monitors

AI搜索引擎品牌引用监测：追踪ChatGPT/Perplexity/Google AI/百度AI/
小红书等平台对品牌的提及情况，记录提及位置、竞对提及、情感倾向。
支持周期性批量检测。

Revision ID: v321_ai_citation_monitors
Revises: v320_geo_brand_profiles
Create Date: 2026-04-25
"""
from alembic import op

revision = "v321_ai_citation_monitors"
down_revision = "v320_geo_brand_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_citation_monitors (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            query               VARCHAR(500) NOT NULL,
            platform            VARCHAR(30) NOT NULL
                                CHECK (platform IN (
                                    'chatgpt', 'perplexity', 'google_ai',
                                    'baidu_ai', 'xiaohongshu'
                                )),
            mention_found       BOOLEAN DEFAULT FALSE,
            mention_text        TEXT,
            mention_position    INT,
            competitor_mentions JSONB DEFAULT '[]',
            sentiment           VARCHAR(20) DEFAULT 'neutral',
            checked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            check_round         INT DEFAULT 1,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_citation_monitors_query_platform
            ON ai_citation_monitors(tenant_id, query, platform, check_round)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_citation_monitors_mention
            ON ai_citation_monitors(tenant_id, mention_found)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE ai_citation_monitors ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ai_citation_monitors_tenant_isolation ON ai_citation_monitors;
        CREATE POLICY ai_citation_monitors_tenant_isolation ON ai_citation_monitors
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE ai_citation_monitors FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_citation_monitors CASCADE")
