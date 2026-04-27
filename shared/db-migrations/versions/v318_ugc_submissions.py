"""v318 — UGC投稿表: ugc_submissions

顾客UGC内容投稿，含AI质量评分、审核流程、互动计数：
media_urls(照片/视频)、ai_quality_score(AI评分)、
审核流程(pending_review→approved→published)、互动统计(view/like/share)。

Revision ID: v318_ugc_submissions
Revises: v317_nps_surveys
Create Date: 2026-04-25
"""
from alembic import op

revision = "v318_ugc_submissions"
down_revision = "v317_nps_surveys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ugc_submissions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            order_id            UUID,
            store_id            UUID NOT NULL,
            media_urls          JSONB NOT NULL DEFAULT '[]',
            caption             TEXT,
            dish_ids            JSONB DEFAULT '[]',
            ai_quality_score    FLOAT,
            ai_quality_feedback TEXT,
            ai_reviewed_at      TIMESTAMPTZ,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending_review'
                                CHECK (status IN (
                                    'pending_review', 'approved', 'rejected',
                                    'published', 'hidden'
                                )),
            rejection_reason    TEXT,
            points_awarded      INT DEFAULT 0,
            view_count          INT DEFAULT 0,
            like_count          INT DEFAULT 0,
            share_count         INT DEFAULT 0,
            featured            BOOLEAN DEFAULT FALSE,
            published_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ugc_submissions_store_status
            ON ugc_submissions(tenant_id, store_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ugc_submissions_customer
            ON ugc_submissions(tenant_id, customer_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ugc_submissions_featured
            ON ugc_submissions(tenant_id, featured)
            WHERE featured = true AND is_deleted = false
    """)

    op.execute("ALTER TABLE ugc_submissions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ugc_submissions_tenant_isolation ON ugc_submissions;
        CREATE POLICY ugc_submissions_tenant_isolation ON ugc_submissions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE ugc_submissions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ugc_submissions CASCADE")
