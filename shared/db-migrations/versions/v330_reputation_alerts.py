"""v330 — 舆情预警表: reputation_alerts

AI舆情监控与危机预警 S4W15-16：
  实时监测品牌在各社交/点评平台的舆情，
  负面口碑激增自动预警，AI生成危机回应建议，
  SLA响应时间追踪，多级升级机制。

Revision ID: v330_reputation_alerts
Revises: v329_group_deal_participants
Create Date: 2026-04-25
"""
from alembic import op

revision = "v330_reputation_alerts"
down_revision = "v329_group_deal_participants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS reputation_alerts (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID,
            platform                VARCHAR(30) NOT NULL
                                    CHECK (platform IN (
                                        'weibo', 'xiaohongshu', 'douyin',
                                        'dianping', 'meituan', 'wechat', 'google'
                                    )),
            alert_type              VARCHAR(30) NOT NULL
                                    CHECK (alert_type IN (
                                        'negative_spike', 'crisis', 'trending_negative',
                                        'rating_drop', 'competitor_attack'
                                    )),
            severity                VARCHAR(20) NOT NULL DEFAULT 'medium'
                                    CHECK (severity IN (
                                        'low', 'medium', 'high', 'critical'
                                    )),
            trigger_mention_ids     JSONB NOT NULL DEFAULT '[]',
            trigger_data            JSONB NOT NULL DEFAULT '{}',
            summary                 TEXT NOT NULL,
            recommended_actions     JSONB NOT NULL DEFAULT '[]',
            response_status         VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (response_status IN (
                                        'pending', 'acknowledged', 'responding',
                                        'escalated', 'resolved', 'dismissed'
                                    )),
            response_text           TEXT,
            responded_at            TIMESTAMPTZ,
            response_time_sec       INT,
            sla_target_sec          INT NOT NULL DEFAULT 1800,
            sla_met                 BOOLEAN,
            assigned_to             UUID,
            escalated_to            UUID,
            escalated_at            TIMESTAMPTZ,
            resolved_at             TIMESTAMPTZ,
            resolution_note         TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rep_alerts_status_severity
            ON reputation_alerts(tenant_id, response_status, severity DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rep_alerts_store_created
            ON reputation_alerts(tenant_id, store_id, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rep_alerts_sla_missed
            ON reputation_alerts(tenant_id, sla_met)
            WHERE sla_met = false AND is_deleted = false
    """)

    op.execute("ALTER TABLE reputation_alerts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS reputation_alerts_tenant_isolation ON reputation_alerts;
        CREATE POLICY reputation_alerts_tenant_isolation ON reputation_alerts
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE reputation_alerts FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reputation_alerts CASCADE")
