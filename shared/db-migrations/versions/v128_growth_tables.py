"""v128 — 增长营销核心表

新增五张表：
  coupons              — 优惠券模板
  customer_coupons     — 顾客领券记录
  campaigns            — 营销活动
  notification_tasks   — 异步通知任务
  anomaly_dismissals   — 异常已知悉记录（tx-intel）

字段命名与路由文件实际 SQL 完全对齐：
  coupon_routes.py       → coupons / customer_coupons
  growth_campaign_routes → campaigns
  notification_routes    → notification_tasks
  anomaly_routes         → anomaly_dismissals

Revision ID: v128
Revises: v127
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v128"
down_revision = "v127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── coupons 优惠券模板 ────────────────────────────────────────
    # 字段对齐 coupon_routes.py：
    #   discount_rate / cash_amount_fen / max_claim_per_user /
    #   claimed_count / expiry_days / start_date / end_date / is_active
    if "coupons" not in _existing:
        op.create_table(
            "coupons",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("coupon_type", sa.String(30), nullable=False),
            # coupon_routes.py SELECT: discount_rate, cash_amount_fen
            sa.Column("discount_rate", sa.Numeric(5, 4), nullable=True),
            sa.Column("cash_amount_fen", sa.Integer, nullable=True),
            sa.Column("min_order_fen", sa.Integer, nullable=False, server_default="0"),
            # coupon_routes.py SELECT: max_claim_per_user
            sa.Column("max_claim_per_user", sa.Integer, nullable=False, server_default="1"),
            # coupon_routes.py SELECT: total_quantity, claimed_count
            sa.Column("total_quantity", sa.Integer, nullable=True),
            sa.Column("claimed_count", sa.Integer, nullable=False, server_default="0"),
            # coupon_routes.py SELECT: expiry_days
            sa.Column("expiry_days", sa.Integer, nullable=True),
            # coupon_routes.py SELECT: start_date, end_date
            sa.Column("start_date", sa.Date, nullable=True),
            sa.Column("end_date", sa.Date, nullable=True),
            sa.Column("applicable_scope", sa.String(20), nullable=False, server_default="'all'"),
            sa.Column("applicable_ids", JSONB, nullable=True),
            # coupon_routes.py WHERE: is_active = true
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='coupons' AND column_name IN ('tenant_id', 'is_active')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_coupons_tenant_active ON coupons (tenant_id, is_active)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE coupons ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS coupons_tenant_isolation ON coupons;")
    op.execute("DROP POLICY IF EXISTS coupons_tenant_isolation ON coupons;")
    op.execute("""
        CREATE POLICY coupons_tenant_isolation ON coupons
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── customer_coupons 顾客领券记录 ────────────────────────────
    # 字段对齐 coupon_routes.py INSERT:
    #   id, tenant_id, coupon_id, customer_id, status,
    #   claimed_at, expire_at, created_at, updated_at
    if "customer_coupons" not in _existing:
        op.create_table(
            "customer_coupons",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("coupon_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
            # coupon_routes.py: status='unused'/'used'/'expired'
            sa.Column("status", sa.String(20), nullable=False, server_default="'unused'"),
            sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("order_id", UUID(as_uuid=True), nullable=True),
            sa.Column("expire_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='customer_coupons' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_customer_coupons_customer ON customer_coupons (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='customer_coupons' AND column_name IN ('coupon_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_customer_coupons_coupon ON customer_coupons (coupon_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE customer_coupons ADD CONSTRAINT fk_customer_coupons_coupon
                FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE customer_coupons ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS customer_coupons_tenant_isolation ON customer_coupons;")
    op.execute("DROP POLICY IF EXISTS customer_coupons_tenant_isolation ON customer_coupons;")
    op.execute("""
        CREATE POLICY customer_coupons_tenant_isolation ON customer_coupons
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── campaigns 营销活动 ────────────────────────────────────────
    # 字段对齐 growth_campaign_routes.py SELECT:
    #   id, campaign_type, name, description, status, config,
    #   start_time, end_time, budget_fen, spent_fen,
    #   target_segments, participant_count, reward_count,
    #   total_cost_fen, conversion_count, created_at, updated_at
    if "campaigns" not in _existing:
        op.create_table(
            "campaigns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("campaign_type", sa.String(30), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="'draft'"),
            sa.Column("description", sa.Text, nullable=True),
            # growth_campaign_routes.py: start_time / end_time（注意非 start_at）
            sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("budget_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("spent_fen", sa.Integer, nullable=False, server_default="0"),
            # growth_campaign_routes.py: target_segments (JSONB 数组)
            sa.Column("target_segments", JSONB, nullable=True),
            # growth_campaign_routes.py stats: participant_count / reward_count / total_cost_fen
            sa.Column("participant_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("reward_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_cost_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("conversion_count", sa.Integer, nullable=False, server_default="0"),
            # growth_campaign_routes.py: config JSONB（存 rules 等扩展字段）
            sa.Column("config", JSONB, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='campaigns' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_campaigns_tenant_status ON campaigns (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='campaigns' AND column_name IN ('tenant_id', 'start_time', 'end_time')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_campaigns_tenant_time ON campaigns (tenant_id, start_time, end_time)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS campaigns_tenant_isolation ON campaigns;")
    op.execute("DROP POLICY IF EXISTS campaigns_tenant_isolation ON campaigns;")
    op.execute("""
        CREATE POLICY campaigns_tenant_isolation ON campaigns
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── notification_tasks 异步通知任务 ─────────────────────────
    # 字段对齐 notification_routes.py INSERT / SELECT:
    #   id, tenant_id, campaign_id, channel, message_template,
    #   target_customer_ids, status, total_count,
    #   sent_count, failed_count, created_at, updated_at
    if "notification_tasks" not in _existing:
        op.create_table(
            "notification_tasks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), nullable=True),
            # notification_routes.py: channel in {sms, wechat_template, miniapp_push}
            sa.Column("channel", sa.String(30), nullable=False),
            # notification_routes.py INSERT: message_template
            sa.Column("message_template", sa.Text, nullable=True),
            # notification_routes.py INSERT: target_customer_ids::jsonb
            sa.Column("target_customer_ids", JSONB, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
            sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
            # notification_routes.py SELECT: sent_count / failed_count（非 success_count）
            sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notification_tasks' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notification_tasks_tenant_status ON notification_tasks (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='notification_tasks' AND (column_name = 'campaign_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_notification_tasks_campaign ON notification_tasks (campaign_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE notification_tasks ADD CONSTRAINT fk_notification_tasks_campaign
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE notification_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS notification_tasks_tenant_isolation ON notification_tasks;")
    op.execute("DROP POLICY IF EXISTS notification_tasks_tenant_isolation ON notification_tasks;")
    op.execute("""
        CREATE POLICY notification_tasks_tenant_isolation ON notification_tasks
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── anomaly_dismissals 异常已知悉记录（tx-intel）────────────
    if "anomaly_dismissals" not in _existing:
        op.create_table(
            "anomaly_dismissals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("anomaly_id", sa.String(100), nullable=False),
            sa.Column("dismissed_by", sa.String(100), nullable=True),
            sa.Column("dismissed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='anomaly_dismissals' AND column_name IN ('tenant_id', 'anomaly_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_anomaly_dismissals_tenant ON anomaly_dismissals (tenant_id, anomaly_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE anomaly_dismissals ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS anomaly_dismissals_tenant_isolation ON anomaly_dismissals;")
    op.execute("DROP POLICY IF EXISTS anomaly_dismissals_tenant_isolation ON anomaly_dismissals;")
    op.execute("""
        CREATE POLICY anomaly_dismissals_tenant_isolation ON anomaly_dismissals
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    # 逆序删除，先删依赖表
    op.execute("DROP POLICY IF EXISTS anomaly_dismissals_tenant_isolation ON anomaly_dismissals;")
    op.drop_table("anomaly_dismissals")

    op.execute("DROP POLICY IF EXISTS notification_tasks_tenant_isolation ON notification_tasks;")
    op.drop_table("notification_tasks")

    op.execute("DROP POLICY IF EXISTS campaigns_tenant_isolation ON campaigns;")
    op.drop_table("campaigns")

    op.execute("DROP POLICY IF EXISTS customer_coupons_tenant_isolation ON customer_coupons;")
    op.drop_table("customer_coupons")

    op.execute("DROP POLICY IF EXISTS coupons_tenant_isolation ON coupons;")
    op.drop_table("coupons")
