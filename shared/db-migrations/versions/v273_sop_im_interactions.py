"""v273 — sop_im_interactions（Phase S2: IM全闭环升级）

新建表：
  - sop_im_interactions: IM交互记录（任务卡/快捷回复/照片上传/语音指令/教练卡/预警卡）

Revision ID: v273_sop_im_interactions
Revises: v272_sop_corrective
Create Date: 2026-04-23
"""

from alembic import op

revision = "v273_sop_im_interactions"
down_revision = "v272_sop_corrective"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_im_interactions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_im_interactions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            user_id         UUID NOT NULL,
            instance_id     UUID REFERENCES sop_task_instances(id),
            action_id       UUID REFERENCES sop_corrective_actions(id),
            channel         TEXT NOT NULL,
            direction       TEXT NOT NULL,
            message_type    TEXT NOT NULL,
            content         JSONB NOT NULL,
            reply_to        UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_im_interactions_store_user
            ON sop_im_interactions (store_id, user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_im_interactions_instance
            ON sop_im_interactions (instance_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_im_interactions_action
            ON sop_im_interactions (action_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_im_interactions_created
            ON sop_im_interactions (created_at DESC)
    """)

    # RLS
    op.execute("ALTER TABLE sop_im_interactions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_im_interactions_tenant ON sop_im_interactions")
    op.execute("""
        CREATE POLICY sop_im_interactions_tenant ON sop_im_interactions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_im_interactions IS
            'Phase S2: IM交互记录 — 所有SOP↔IM双向消息的审计日志';
        COMMENT ON COLUMN sop_im_interactions.channel IS
            'IM通道：wecom / dingtalk / feishu';
        COMMENT ON COLUMN sop_im_interactions.direction IS
            '消息方向：outbound（推送到IM） / inbound（从IM回调）';
        COMMENT ON COLUMN sop_im_interactions.message_type IS
            '消息类型：task_card / quick_reply / photo_upload / voice_cmd / coaching_card / alert_card';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS sop_im_interactions_tenant ON sop_im_interactions")
    op.execute("ALTER TABLE IF EXISTS sop_im_interactions DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_sop_im_interactions_created")
    op.execute("DROP INDEX IF EXISTS idx_sop_im_interactions_action")
    op.execute("DROP INDEX IF EXISTS idx_sop_im_interactions_instance")
    op.execute("DROP INDEX IF EXISTS idx_sop_im_interactions_store_user")
    op.execute("DROP TABLE IF EXISTS sop_im_interactions")
