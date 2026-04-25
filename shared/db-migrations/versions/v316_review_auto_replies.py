"""v316 — AI评论自动回复表: review_auto_replies

AI生成的品牌语调评论回复，关联order_reviews：
generated_reply(AI生成)、brand_voice_config(品牌语调配置)、
审批流程(draft→approved→posted)。

Revision ID: v316_review_auto_replies
Revises: v315_external_order_imports
Create Date: 2026-04-25
"""
from alembic import op

revision = "v316_review_auto_replies"
down_revision = "v315_external_order_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS review_auto_replies (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            review_id           UUID NOT NULL,
            platform            VARCHAR(30) NOT NULL
                                CHECK (platform IN (
                                    'dianping', 'meituan', 'douyin', 'google', 'xiaohongshu'
                                )),
            original_rating     FLOAT,
            original_text       TEXT,
            generated_reply     TEXT NOT NULL,
            brand_voice_config  JSONB DEFAULT '{}',
            model_used          VARCHAR(50) DEFAULT 'claude-haiku',
            status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                                CHECK (status IN (
                                    'draft', 'approved', 'posted', 'failed', 'expired'
                                )),
            approved_by         UUID,
            approved_at         TIMESTAMPTZ,
            posted_at           TIMESTAMPTZ,
            failure_reason      TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_review_auto_replies_review
            ON review_auto_replies(tenant_id, review_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_review_auto_replies_status
            ON review_auto_replies(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_review_auto_replies_platform_time
            ON review_auto_replies(tenant_id, platform, created_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE review_auto_replies ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS review_auto_replies_tenant_isolation ON review_auto_replies;
        CREATE POLICY review_auto_replies_tenant_isolation ON review_auto_replies
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE review_auto_replies FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS review_auto_replies CASCADE")
