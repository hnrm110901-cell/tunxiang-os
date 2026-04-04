"""v144 — 优惠策略/渠道配置/内容模板 DB 化

新增 5 张表：
  offers              — 优惠策略主表（替换 offer_engine.py 内存存储）
  offer_redemptions   — 优惠核销记录
  channel_configs     — 渠道配置（企微/短信/小程序等）
  message_send_logs   — 消息发送日志（替换 channel_engine.py 内存 _send_logs）
  content_templates   — 内容模板库（替换 content_engine.py 内存 _templates）

Revision ID: v144
Revises: v143
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v144"
down_revision = "v143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── offers 优惠策略主表 ────────────────────────────────────────
    if "offers" not in _existing:
        op.create_table(
            "offers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("offer_type", sa.String(40), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("goal", sa.String(30), nullable=True),
            sa.Column("discount_rules", JSONB, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("validity_days", sa.Integer, nullable=False, server_default="30"),
            sa.Column("target_segments", JSONB, nullable=True),
            sa.Column("applicable_stores", JSONB, nullable=True),
            sa.Column("time_slots", JSONB, nullable=True),
            sa.Column("margin_floor", sa.Numeric(5, 4), nullable=False, server_default="0.45"),
            sa.Column("max_per_user", sa.Integer, nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("issued_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("redeemed_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_discount_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='offers' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_offers_tenant_status ON offers (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='offers' AND column_name IN ('tenant_id', 'offer_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_offers_tenant_type ON offers (tenant_id, offer_type)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE offers ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS offers_tenant_isolation ON offers;")
    op.execute("DROP POLICY IF EXISTS offers_tenant_isolation ON offers;")
    op.execute("""
        CREATE POLICY offers_tenant_isolation ON offers
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── offer_redemptions 优惠核销记录 ────────────────────────────
    if "offer_redemptions" not in _existing:
        op.create_table(
            "offer_redemptions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("offer_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=True),
            sa.Column("order_total_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("discount_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("redeemed_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='offer_redemptions' AND column_name IN ('tenant_id', 'offer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_offer_redemptions_offer ON offer_redemptions (tenant_id, offer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='offer_redemptions' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_offer_redemptions_customer ON offer_redemptions (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE offer_redemptions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS offer_redemptions_tenant_isolation ON offer_redemptions;")
    op.execute("DROP POLICY IF EXISTS offer_redemptions_tenant_isolation ON offer_redemptions;")
    op.execute("""
        CREATE POLICY offer_redemptions_tenant_isolation ON offer_redemptions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── channel_configs 渠道配置 ─────────────────────────────────
    if "channel_configs" not in _existing:
        op.create_table(
            "channel_configs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("channel", sa.String(30), nullable=False),
            sa.Column("max_daily_per_user", sa.Integer, nullable=False, server_default="3"),
            sa.Column("settings", JSONB, nullable=True),
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.UniqueConstraint("tenant_id", "channel", name="uq_channel_configs_tenant_channel"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='channel_configs' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_channel_configs_tenant ON channel_configs (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE channel_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS channel_configs_tenant_isolation ON channel_configs;")
    op.execute("DROP POLICY IF EXISTS channel_configs_tenant_isolation ON channel_configs;")
    op.execute("""
        CREATE POLICY channel_configs_tenant_isolation ON channel_configs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── message_send_logs 消息发送日志 ────────────────────────────
    if "message_send_logs" not in _existing:
        op.create_table(
            "message_send_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("channel", sa.String(30), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=True),
            sa.Column("external_user_id", sa.String(200), nullable=True),
            sa.Column("content_summary", sa.Text, nullable=True),
            sa.Column("offer_id", UUID(as_uuid=True), nullable=True),
            sa.Column("campaign_id", UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'sent'")),
            sa.Column("error_reason", sa.Text, nullable=True),
            sa.Column("sent_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='message_send_logs' AND column_name IN ('tenant_id', 'channel')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_message_send_logs_tenant_channel ON message_send_logs (tenant_id, channel)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='message_send_logs' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_message_send_logs_customer ON message_send_logs (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='message_send_logs' AND column_name IN ('tenant_id', 'sent_at')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_message_send_logs_sent_at ON message_send_logs (tenant_id, sent_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE message_send_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS message_send_logs_tenant_isolation ON message_send_logs;")
    op.execute("DROP POLICY IF EXISTS message_send_logs_tenant_isolation ON message_send_logs;")
    op.execute("""
        CREATE POLICY message_send_logs_tenant_isolation ON message_send_logs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── content_templates 内容模板库 ──────────────────────────────
    if "content_templates" not in _existing:
        op.create_table(
            "content_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("template_key", sa.String(80), nullable=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("content_type", sa.String(40), nullable=False),
            sa.Column("body_template", sa.Text, nullable=False),
            sa.Column("variables", JSONB, nullable=True),
            sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.UniqueConstraint(
                "tenant_id", "template_key",
                name="uq_content_templates_tenant_key",
            ),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='content_templates' AND column_name IN ('tenant_id', 'content_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_content_templates_tenant_type ON content_templates (tenant_id, content_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='content_templates' AND column_name IN ('tenant_id', 'template_key')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_content_templates_tenant_key ON content_templates (tenant_id, template_key)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE content_templates ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS content_templates_tenant_isolation ON content_templates;")
    op.execute("DROP POLICY IF EXISTS content_templates_tenant_isolation ON content_templates;")
    op.execute("""
        CREATE POLICY content_templates_tenant_isolation ON content_templates
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS content_templates_tenant_isolation ON content_templates;"
    )
    op.drop_table("content_templates")

    op.execute(
        "DROP POLICY IF EXISTS message_send_logs_tenant_isolation ON message_send_logs;"
    )
    op.drop_table("message_send_logs")

    op.execute(
        "DROP POLICY IF EXISTS channel_configs_tenant_isolation ON channel_configs;"
    )
    op.drop_table("channel_configs")

    op.execute(
        "DROP POLICY IF EXISTS offer_redemptions_tenant_isolation ON offer_redemptions;"
    )
    op.drop_table("offer_redemptions")

    op.execute(
        "DROP POLICY IF EXISTS offers_tenant_isolation ON offers;"
    )
    op.drop_table("offers")
