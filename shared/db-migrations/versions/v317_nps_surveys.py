"""v317 — NPS调查表: nps_surveys

客户NPS调查记录，支持自动计算推荐者/贬损者：
nps_score(0-10)、feedback_text(反馈文本)、tags(自动提取主题)、
is_promoter/is_detractor(生成列)。

Revision ID: v317_nps_surveys
Revises: v316_review_auto_replies
Create Date: 2026-04-25
"""
from alembic import op

revision = "v317_nps_surveys"
down_revision = "v316_review_auto_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS nps_surveys (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            store_id            UUID NOT NULL,
            order_id            UUID,
            nps_score           INT CHECK (nps_score >= 0 AND nps_score <= 10),
            feedback_text       TEXT,
            tags                JSONB DEFAULT '[]',
            channel             VARCHAR(30) DEFAULT 'wechat',
            sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            responded_at        TIMESTAMPTZ,
            response_time_sec   INT,
            is_promoter         BOOLEAN GENERATED ALWAYS AS (nps_score >= 9) STORED,
            is_detractor        BOOLEAN GENERATED ALWAYS AS (nps_score <= 6) STORED,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_nps_surveys_store_sent
            ON nps_surveys(tenant_id, store_id, sent_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_nps_surveys_customer
            ON nps_surveys(tenant_id, customer_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_nps_surveys_score
            ON nps_surveys(tenant_id, nps_score)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE nps_surveys ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS nps_surveys_tenant_isolation ON nps_surveys;
        CREATE POLICY nps_surveys_tenant_isolation ON nps_surveys
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE nps_surveys FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS nps_surveys CASCADE")
