"""v133 — 地址簿 + 通知消息 + 通知模板

新增三张表：
  customer_addresses     — 客户地址簿
  notifications          — 通知消息（多渠道、多目标）
  notification_templates — 通知模板

Revision ID: v133
Revises: v132
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v133"
down_revision = "v132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── customer_addresses 客户地址簿 ─────────────────────────────
    if "customer_addresses" not in _existing:
        op.create_table(
            "customer_addresses",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("phone", sa.String(20), nullable=False),
            sa.Column("province", sa.String(30), nullable=False, server_default=""),
            sa.Column("city", sa.String(30), nullable=False, server_default=""),
            sa.Column("district", sa.String(30), nullable=False, server_default=""),
            sa.Column("detail_address", sa.String(200), nullable=False, server_default=""),
            sa.Column("location_lng", sa.Numeric(10, 7), nullable=True),
            sa.Column("location_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("tag", sa.String(20), nullable=False, server_default="home"),
            sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='customer_addresses' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_customer_addresses_tenant_customer ON customer_addresses (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='customer_addresses' AND column_name IN ('tenant_id', 'phone')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_customer_addresses_tenant_phone ON customer_addresses (tenant_id, phone)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE customer_addresses ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS customer_addresses_tenant_isolation ON customer_addresses;")
    op.execute("DROP POLICY IF EXISTS customer_addresses_tenant_isolation ON customer_addresses;")
    op.execute("""
        CREATE POLICY customer_addresses_tenant_isolation ON customer_addresses
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── notifications 通知消息 ────────────────────────────────────
    if "notifications" not in _existing:
        op.create_table(
            "notifications",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("target_type", sa.String(20), nullable=False),
            sa.Column("target_id", UUID(as_uuid=True), nullable=True),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("title", sa.String(100), nullable=False),
            sa.Column("content", sa.Text, nullable=False, server_default=""),
            sa.Column("category", sa.String(30), nullable=False, server_default="system"),
            sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("metadata", JSONB, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name IN ('tenant_id', 'target_type', 'target_id')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notifications_tenant_target ON notifications (tenant_id, target_type, target_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name IN ('tenant_id', 'category')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notifications_tenant_category ON notifications (tenant_id, category)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notifications_tenant_status ON notifications (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name IN ('tenant_id', 'priority')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notifications_tenant_priority ON notifications (tenant_id, priority)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notifications' AND (column_name = 'created_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications;")
    op.execute("DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications;")
    op.execute("""
        CREATE POLICY notifications_tenant_isolation ON notifications
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── notification_templates 通知模板 ───────────────────────────
    if "notification_templates" not in _existing:
        op.create_table(
            "notification_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("category", sa.String(30), nullable=False, server_default="system"),
            sa.Column("title_template", sa.String(200), nullable=False, server_default=""),
            sa.Column("content_template", sa.Text, nullable=False, server_default=""),
            sa.Column("variables", JSONB, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notification_templates' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notification_templates_tenant ON notification_templates (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notification_templates' AND (column_name = 'code')) = 1 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_notification_templates_code ON notification_templates (code)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notification_templates' AND column_name IN ('tenant_id', 'channel')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notification_templates_tenant_channel ON notification_templates (tenant_id, channel)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS notification_templates_tenant_isolation ON notification_templates;")
    op.execute("DROP POLICY IF EXISTS notification_templates_tenant_isolation ON notification_templates;")
    op.execute("""
        CREATE POLICY notification_templates_tenant_isolation ON notification_templates
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS notification_templates_tenant_isolation ON notification_templates;")
    op.drop_table("notification_templates")
    op.execute("DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications;")
    op.drop_table("notifications")
    op.execute("DROP POLICY IF EXISTS customer_addresses_tenant_isolation ON customer_addresses;")
    op.drop_table("customer_addresses")
