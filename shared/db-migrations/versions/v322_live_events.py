"""v322 — 直播活动表: live_events

视频号+直播模块 S3W10-11：
  直播活动管理（微信视频号/抖音/快手/小红书），
  记录直播间全生命周期（scheduled→live→ended/cancelled），
  实时指标（观看人数/点赞/评论/优惠券分发/营收归因）。

Revision ID: v322_live_events
Revises: v321_ai_citation_monitors
Create Date: 2026-04-25
"""
from alembic import op

revision = "v322_live_events"
down_revision = "v321_ai_citation_monitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_events (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            store_id                    UUID,
            platform                    VARCHAR(30) NOT NULL
                                        CHECK (platform IN (
                                            'wechat_video', 'douyin',
                                            'kuaishou', 'xiaohongshu'
                                        )),
            live_room_id                VARCHAR(100),
            title                       VARCHAR(200) NOT NULL,
            description                 TEXT,
            cover_image_url             VARCHAR(500),
            host_employee_id            UUID,
            status                      VARCHAR(20) NOT NULL DEFAULT 'scheduled'
                                        CHECK (status IN (
                                            'scheduled', 'live',
                                            'ended', 'cancelled'
                                        )),
            scheduled_at                TIMESTAMPTZ NOT NULL,
            started_at                  TIMESTAMPTZ,
            ended_at                    TIMESTAMPTZ,
            viewer_count                INT DEFAULT 0,
            peak_viewer_count           INT DEFAULT 0,
            like_count                  INT DEFAULT 0,
            comment_count               INT DEFAULT 0,
            coupon_total_distributed    INT DEFAULT 0,
            coupon_total_redeemed       INT DEFAULT 0,
            revenue_attributed_fen      BIGINT DEFAULT 0,
            new_followers_count         INT DEFAULT 0,
            recording_url               VARCHAR(500),
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_events_status_scheduled
            ON live_events(tenant_id, status, scheduled_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_events_store
            ON live_events(tenant_id, store_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE live_events ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS live_events_tenant_isolation ON live_events;
        CREATE POLICY live_events_tenant_isolation ON live_events
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE live_events FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS live_events CASCADE")
