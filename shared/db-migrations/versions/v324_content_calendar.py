"""v324 — 内容日历表: content_calendar

智能内容工厂 S3W11-12：
  内容日历管理与AI自动生成，支持朋友圈/企微/短信/海报/短视频脚本/
  菜品故事/时令活动/直播预告等内容类型，集成Claude AI生成能力，
  统一排期与多渠道发布。

Revision ID: v324_content_calendar
Revises: v323_live_coupons
Create Date: 2026-04-25
"""
from alembic import op

revision = "v324_content_calendar"
down_revision = "v323_live_coupons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS content_calendar (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            title               VARCHAR(200) NOT NULL,
            content_type        VARCHAR(30) NOT NULL
                                CHECK (content_type IN (
                                    'moments', 'wecom_chat', 'sms',
                                    'poster', 'short_video_script',
                                    'dish_story', 'seasonal_campaign',
                                    'live_preview'
                                )),
            content_body        TEXT NOT NULL,
            media_urls          JSONB NOT NULL DEFAULT '[]',
            target_channels     JSONB NOT NULL DEFAULT '[]',
            tags                JSONB NOT NULL DEFAULT '[]',
            ai_generated        BOOLEAN NOT NULL DEFAULT FALSE,
            ai_model            VARCHAR(50),
            ai_prompt_context   JSONB NOT NULL DEFAULT '{}',
            scheduled_at        TIMESTAMPTZ,
            published_at        TIMESTAMPTZ,
            status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                                CHECK (status IN (
                                    'draft', 'scheduled', 'publishing',
                                    'published', 'failed', 'cancelled'
                                )),
            publish_result      JSONB NOT NULL DEFAULT '{}',
            created_by          UUID,
            approved_by         UUID,
            approved_at         TIMESTAMPTZ,
            view_count          INT NOT NULL DEFAULT 0,
            click_count         INT NOT NULL DEFAULT 0,
            share_count         INT NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_calendar_status_sched
            ON content_calendar(tenant_id, status, scheduled_at)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_calendar_store_type
            ON content_calendar(tenant_id, store_id, content_type)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_calendar_ai_generated
            ON content_calendar(tenant_id, ai_generated)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE content_calendar ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS content_calendar_tenant_isolation ON content_calendar;
        CREATE POLICY content_calendar_tenant_isolation ON content_calendar
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE content_calendar FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_calendar CASCADE")
