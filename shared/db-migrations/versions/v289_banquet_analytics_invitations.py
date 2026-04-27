"""v289 — 宴会分析报表 + 电子邀请函（S7）

4张新表：
  - banquet_analytics_snapshots  — 宴会分析快照（按日/周/月聚合）
  - banquet_lost_reasons         — 宴会丢单原因记录
  - invitation_templates         — 电子邀请函模板
  - invitation_instances         — 电子邀请函实例（发布后可公开访问）

所有表启用 RLS 租户隔离。

Revision ID: v289
Revises: v288
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v289"
down_revision: Union[str, None] = "v288"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════
    # 1. banquet_analytics_snapshots — 宴会分析快照
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_analytics_snapshots (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            snapshot_date       DATE NOT NULL,
            period_type         VARCHAR(10) NOT NULL
                                CHECK (period_type IN ('daily', 'weekly', 'monthly')),
            banquet_type        VARCHAR(30),
                                -- 婚宴/生日宴/宝宝宴/寿宴/商务宴/升学宴/乔迁宴/其他
            total_leads         INTEGER NOT NULL DEFAULT 0,
            converted_leads     INTEGER NOT NULL DEFAULT 0,
            lost_leads          INTEGER NOT NULL DEFAULT 0,
            total_orders        INTEGER NOT NULL DEFAULT 0,
            total_tables        INTEGER NOT NULL DEFAULT 0,
            total_revenue_fen   BIGINT NOT NULL DEFAULT 0,
            avg_table_price_fen BIGINT NOT NULL DEFAULT 0,
            deposit_fen         BIGINT NOT NULL DEFAULT 0,
            final_payment_fen   BIGINT NOT NULL DEFAULT 0,
            source_channel      VARCHAR(50),
                                -- 到店/电话/微信/小程序/转介绍/婚庆公司/抖音/其他
            salesperson_id      UUID,
            salesperson_name    VARCHAR(100),
            extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_snapshots_tenant_date
            ON banquet_analytics_snapshots (tenant_id, store_id, snapshot_date DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_snapshots_type
            ON banquet_analytics_snapshots (tenant_id, banquet_type, period_type)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_analytics_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_analytics_snapshots_tenant_isolation
            ON banquet_analytics_snapshots;
        CREATE POLICY banquet_analytics_snapshots_tenant_isolation
            ON banquet_analytics_snapshots
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 2. banquet_lost_reasons — 宴会丢单原因记录
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_lost_reasons (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            banquet_lead_id     UUID,
                                -- 关联 banquet_leads 表（如有）
            banquet_type        VARCHAR(30),
            reason_category     VARCHAR(50) NOT NULL,
                                -- 价格/档期/菜品/场地/服务/竞品/其他
            reason_detail       TEXT,
            competitor_name     VARCHAR(200),
            lost_revenue_fen    BIGINT NOT NULL DEFAULT 0,
            lost_tables         INTEGER NOT NULL DEFAULT 0,
            salesperson_id      UUID,
            salesperson_name    VARCHAR(100),
            recorded_by         UUID NOT NULL,
            recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_lost_reasons_tenant
            ON banquet_lost_reasons (tenant_id, store_id, recorded_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_lost_reasons_category
            ON banquet_lost_reasons (tenant_id, reason_category)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_lost_reasons ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_lost_reasons_tenant_isolation
            ON banquet_lost_reasons;
        CREATE POLICY banquet_lost_reasons_tenant_isolation
            ON banquet_lost_reasons
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 3. invitation_templates — 电子邀请函模板
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS invitation_templates (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID,
                                -- NULL = 系统预置模板
            template_name       VARCHAR(200) NOT NULL,
            template_code       VARCHAR(50) NOT NULL,
            banquet_type        VARCHAR(30) NOT NULL
                                CHECK (banquet_type IN (
                                    'wedding', 'birthday', 'baby', 'longevity',
                                    'corporate', 'graduation', 'housewarming', 'other'
                                )),
            cover_image_url     TEXT,
            background_color    VARCHAR(20),
            layout_config       JSONB NOT NULL DEFAULT '{}'::jsonb,
                                -- 布局配置：标题/正文/时间地点/RSVP 等区块
            music_url           TEXT,
            animation_type      VARCHAR(30),
                                -- none/fade/slide/flip
            is_system           BOOLEAN NOT NULL DEFAULT FALSE,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order          INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invitation_templates_code
            ON invitation_templates (template_code)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invitation_templates_tenant_type
            ON invitation_templates (tenant_id, banquet_type, is_active)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE invitation_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS invitation_templates_tenant_isolation
            ON invitation_templates;
        CREATE POLICY invitation_templates_tenant_isolation
            ON invitation_templates
            USING (
                tenant_id IS NULL
                OR tenant_id::text = current_setting('app.tenant_id', true)
            )
            WITH CHECK (
                tenant_id::text = current_setting('app.tenant_id', true)
            );
    """)

    # ══════════════════════════════════════════════════════════════
    # 4. invitation_instances — 电子邀请函实例
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS invitation_instances (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            template_id         UUID NOT NULL REFERENCES invitation_templates(id),
            banquet_order_id    UUID,
                                -- 关联宴会订单（可选）
            share_code          VARCHAR(20) NOT NULL,
                                -- 短码，用于公开访问 URL
            title               VARCHAR(200) NOT NULL,
            host_names          VARCHAR(200),
                                -- 主人姓名（新郎新娘/寿星/宝宝等）
            event_date          TIMESTAMPTZ NOT NULL,
            event_address       TEXT,
            event_hall          VARCHAR(100),
                                -- 宴会厅名称
            greeting_text       TEXT,
                                -- 祝福语/邀请正文
            custom_fields       JSONB NOT NULL DEFAULT '{}'::jsonb,
                                -- 自定义字段（菜单预览/交通指引/停车信息等）
            cover_image_url     TEXT,
            gallery_urls        JSONB NOT NULL DEFAULT '[]'::jsonb,
            music_url           TEXT,
            status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'published', 'expired', 'archived')),
            published_at        TIMESTAMPTZ,
            expires_at          TIMESTAMPTZ,
            view_count          INTEGER NOT NULL DEFAULT 0,
            rsvp_yes_count      INTEGER NOT NULL DEFAULT 0,
            rsvp_no_count       INTEGER NOT NULL DEFAULT 0,
            rsvp_total_guests   INTEGER NOT NULL DEFAULT 0,
            rsvp_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
            rsvp_deadline       TIMESTAMPTZ,
            created_by          UUID NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invitation_instances_share_code
            ON invitation_instances (share_code)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invitation_instances_tenant
            ON invitation_instances (tenant_id, store_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invitation_instances_banquet
            ON invitation_instances (tenant_id, banquet_order_id)
            WHERE banquet_order_id IS NOT NULL AND is_deleted = false
    """)

    op.execute("ALTER TABLE invitation_instances ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS invitation_instances_tenant_isolation
            ON invitation_instances;
        CREATE POLICY invitation_instances_tenant_isolation
            ON invitation_instances
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 表注释
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        COMMENT ON TABLE banquet_analytics_snapshots IS
            'S7: 宴会分析快照 — 按日/周/月聚合宴会经营指标';
        COMMENT ON TABLE banquet_lost_reasons IS
            'S7: 宴会丢单原因 — 记录丢单原因/竞品/损失金额';
        COMMENT ON TABLE invitation_templates IS
            'S7: 电子邀请函模板 — 系统预置(tenant_id=NULL) + 租户自定义';
        COMMENT ON TABLE invitation_instances IS
            'S7: 电子邀请函实例 — 发布后通过 share_code 公开访问';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invitation_instances CASCADE")
    op.execute("DROP TABLE IF EXISTS invitation_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_lost_reasons CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_analytics_snapshots CASCADE")
