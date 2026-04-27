"""v319 — 裂变邀请链表: viral_invite_chains

UGC分享裂变链路追踪，记录分享→点击→转化全链路：
share_link_code(短链)、chain depth(裂变深度)、
转化追踪(viewer_registered/converted_order_id/converted_revenue_fen)。

Revision ID: v319_viral_invite_chains
Revises: v318_ugc_submissions
Create Date: 2026-04-25
"""
from alembic import op

revision = "v319_viral_invite_chains"
down_revision = "v318_ugc_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS viral_invite_chains (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            ugc_id                  UUID,
            campaign_id             UUID,
            sharer_customer_id      UUID NOT NULL,
            share_channel           VARCHAR(30) DEFAULT 'wechat'
                                    CHECK (share_channel IN (
                                        'wechat', 'moments', 'wecom',
                                        'douyin', 'xiaohongshu', 'link'
                                    )),
            share_link_code         VARCHAR(50) NOT NULL,
            viewer_customer_id      UUID,
            viewer_registered       BOOLEAN DEFAULT FALSE,
            converted_order_id      UUID,
            converted_revenue_fen   BIGINT DEFAULT 0,
            depth                   INT DEFAULT 0,
            parent_chain_id         UUID,
            clicked_at              TIMESTAMPTZ,
            converted_at            TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_viral_invite_chains_link_code
            ON viral_invite_chains(tenant_id, share_link_code)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_viral_invite_chains_sharer
            ON viral_invite_chains(tenant_id, sharer_customer_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_viral_invite_chains_ugc
            ON viral_invite_chains(tenant_id, ugc_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE viral_invite_chains ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS viral_invite_chains_tenant_isolation ON viral_invite_chains;
        CREATE POLICY viral_invite_chains_tenant_isolation ON viral_invite_chains
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE viral_invite_chains FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS viral_invite_chains CASCADE")
