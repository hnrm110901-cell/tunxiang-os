"""v130 — 评价系统 + 会员等级表

新增四张表：
  order_reviews        — 顾客订单评价
  review_media         — 评价图片/视频附件
  member_tier_configs  — 会员等级配置
  tier_upgrade_logs    — 升降级记录

Revision ID: v130
Revises: v129
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v130"
down_revision = "v129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── order_reviews 订单评价 ────────────────────────────────────
    if "order_reviews" not in _existing:
        op.create_table(
            "order_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=True),
            # 评分
            sa.Column("overall_rating", sa.SmallInteger, nullable=False),
            sa.Column("food_rating", sa.SmallInteger, nullable=True),
            sa.Column("service_rating", sa.SmallInteger, nullable=True),
            sa.Column("environment_rating", sa.SmallInteger, nullable=True),
            sa.Column("speed_rating", sa.SmallInteger, nullable=True),
            # 内容
            sa.Column("content", sa.Text, nullable=True),
            sa.Column("tags", JSONB, nullable=True),
            sa.Column("is_anonymous", sa.Boolean, nullable=False, server_default="false"),
            # 状态
            sa.Column("status", sa.String(20), nullable=False, server_default="'published'"),
            # 商家回复
            sa.Column("merchant_reply", sa.Text, nullable=True),
            sa.Column("merchant_replied_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("replied_by", sa.String(100), nullable=True),
            # 元数据
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='order_reviews' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_order_reviews_tenant_store ON order_reviews (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='order_reviews' AND (column_name = 'order_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_order_reviews_order ON order_reviews (order_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='order_reviews' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_order_reviews_customer ON order_reviews (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='order_reviews' AND column_name IN ('tenant_id', 'overall_rating')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_order_reviews_rating ON order_reviews (tenant_id, overall_rating)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='order_reviews' AND column_name IN ('order_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_order_reviews_order_customer ON order_reviews (order_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE order_reviews ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS order_reviews_tenant_isolation ON order_reviews;")
    op.execute("DROP POLICY IF EXISTS order_reviews_tenant_isolation ON order_reviews;")
    op.execute("""
        CREATE POLICY order_reviews_tenant_isolation ON order_reviews
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── review_media 评价附件 ─────────────────────────────────────
    if "review_media" not in _existing:
        op.create_table(
            "review_media",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("review_id", UUID(as_uuid=True), nullable=False),
            sa.Column("media_type", sa.String(20), nullable=False),
            sa.Column("url", sa.Text, nullable=False),
            sa.Column("thumbnail_url", sa.Text, nullable=True),
            sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='review_media' AND (column_name = 'review_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_review_media_review ON review_media (review_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE review_media ADD CONSTRAINT fk_review_media_review
                FOREIGN KEY (review_id) REFERENCES order_reviews(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE review_media ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS review_media_tenant_isolation ON review_media;")
    op.execute("DROP POLICY IF EXISTS review_media_tenant_isolation ON review_media;")
    op.execute("""
        CREATE POLICY review_media_tenant_isolation ON review_media
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── member_tier_configs 会员等级配置 ─────────────────────────
    if "member_tier_configs" not in _existing:
        op.create_table(
            "member_tier_configs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("level", sa.SmallInteger, nullable=False),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("min_points", sa.Integer, nullable=False, server_default="0"),
            sa.Column("min_spend_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("discount_rate", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("points_multiplier", sa.Numeric(4, 2), nullable=False, server_default="1.00"),
            sa.Column("birthday_bonus_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("free_delivery_threshold_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("benefits", JSONB, nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("icon", sa.String(10), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='member_tier_configs' AND column_name IN ('tenant_id', 'level')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_member_tier_configs_tenant_level ON member_tier_configs (tenant_id, level)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE member_tier_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS member_tier_configs_tenant_isolation ON member_tier_configs;")
    op.execute("DROP POLICY IF EXISTS member_tier_configs_tenant_isolation ON member_tier_configs;")
    op.execute("""
        CREATE POLICY member_tier_configs_tenant_isolation ON member_tier_configs
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── tier_upgrade_logs 升降级日志 ──────────────────────────────
    if "tier_upgrade_logs" not in _existing:
        op.create_table(
            "tier_upgrade_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
            sa.Column("from_tier_id", UUID(as_uuid=True), nullable=True),
            sa.Column("to_tier_id", UUID(as_uuid=True), nullable=False),
            sa.Column("from_tier_name", sa.String(50), nullable=True),
            sa.Column("to_tier_name", sa.String(50), nullable=False),
            sa.Column("trigger", sa.String(30), nullable=False),
            sa.Column("points_at_change", sa.Integer, nullable=True),
            sa.Column("spend_total_fen", sa.BigInteger, nullable=True),
            sa.Column("reason", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='tier_upgrade_logs' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_tier_upgrade_logs_tenant_customer ON tier_upgrade_logs (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='tier_upgrade_logs' AND column_name IN ('tenant_id', 'created_at')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_tier_upgrade_logs_created ON tier_upgrade_logs (tenant_id, created_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE tier_upgrade_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tier_upgrade_logs_tenant_isolation ON tier_upgrade_logs;")
    op.execute("DROP POLICY IF EXISTS tier_upgrade_logs_tenant_isolation ON tier_upgrade_logs;")
    op.execute("""
        CREATE POLICY tier_upgrade_logs_tenant_isolation ON tier_upgrade_logs
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tier_upgrade_logs_tenant_isolation ON tier_upgrade_logs;")
    op.drop_table("tier_upgrade_logs")

    op.execute("DROP POLICY IF EXISTS member_tier_configs_tenant_isolation ON member_tier_configs;")
    op.drop_table("member_tier_configs")

    op.execute("DROP POLICY IF EXISTS review_media_tenant_isolation ON review_media;")
    op.drop_table("review_media")

    op.execute("DROP POLICY IF EXISTS order_reviews_tenant_isolation ON order_reviews;")
    op.drop_table("order_reviews")
