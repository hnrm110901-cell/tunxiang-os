"""v320 — GEO品牌档案表: geo_brand_profiles

GEO搜索优化模块：门店结构化数据管理，支持Schema.org Restaurant JSON-LD、
AI引擎品牌引用监测、SEO评分体系。覆盖Google/百度/ChatGPT/Perplexity/
小红书/大众点评等平台。

Revision ID: v320_geo_brand_profiles
Revises: v319_viral_invite_chains
Create Date: 2026-04-25
"""
from alembic import op

revision = "v320_geo_brand_profiles"
down_revision = "v319_viral_invite_chains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS geo_brand_profiles (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            platform            VARCHAR(30) NOT NULL
                                CHECK (platform IN (
                                    'google', 'baidu', 'chatgpt',
                                    'perplexity', 'xiaohongshu', 'dianping'
                                )),
            structured_data     JSONB NOT NULL DEFAULT '{}',
            store_name          VARCHAR(200),
            address             TEXT,
            phone               VARCHAR(30),
            cuisine_type        VARCHAR(100),
            latitude            FLOAT,
            longitude           FLOAT,
            business_hours      JSONB DEFAULT '{}',
            menu_highlights     JSONB DEFAULT '[]',
            last_crawl_check    TIMESTAMPTZ,
            citation_found      BOOLEAN DEFAULT FALSE,
            citation_context    TEXT,
            citation_sentiment  VARCHAR(20),
            seo_score           INT DEFAULT 0
                                CHECK (seo_score >= 0 AND seo_score <= 100),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_brand_profiles_store_platform
            ON geo_brand_profiles(tenant_id, store_id, platform)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_geo_brand_profiles_seo_score
            ON geo_brand_profiles(tenant_id, seo_score DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE geo_brand_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS geo_brand_profiles_tenant_isolation ON geo_brand_profiles;
        CREATE POLICY geo_brand_profiles_tenant_isolation ON geo_brand_profiles
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE geo_brand_profiles FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS geo_brand_profiles CASCADE")
