"""v345 -- 积分商城增强 (Points Mall Enhancements)

- points_mall_categories: 商品分类表
- points_mall_achievement_configs: 成就配置表(替代硬编码)
- points_mall_products: 新增 category_id / scope_type / scope_store_ids / image_url
- points_mall_orders: 新增 fulfillment_status / shipping_info / expired_at

Revision: v345_mall_enhancements
"""

from alembic import op

revision = "v345_mall_enhancements"
down_revision = "v344_banquet_aftercare"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 商品分类表 ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS points_mall_categories (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            category_name   VARCHAR(50)     NOT NULL,
            category_code   VARCHAR(30)     NOT NULL,
            icon_url        VARCHAR(500),
            sort_order      INT             NOT NULL DEFAULT 0,
            is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT points_mall_categories_pkey PRIMARY KEY (id),
            CONSTRAINT pmc_tenant_code_uq UNIQUE (tenant_id, category_code)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pmc_tenant_sort "
        "ON points_mall_categories (tenant_id, sort_order)"
    )
    op.execute("ALTER TABLE points_mall_categories ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS points_mall_categories_tenant_isolation "
        "ON points_mall_categories"
    )
    op.execute("""
        CREATE POLICY points_mall_categories_tenant_isolation
            ON points_mall_categories
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)

    # ── 2. 成就配置表 ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS points_mall_achievement_configs (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            achievement_code    VARCHAR(50)     NOT NULL,
            achievement_name    VARCHAR(100)    NOT NULL,
            description         TEXT,
            trigger_type        VARCHAR(30)     NOT NULL,
            trigger_threshold   INT             NOT NULL DEFAULT 1,
            reward_points       INT             NOT NULL DEFAULT 0,
            badge_icon_url      VARCHAR(500),
            is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
            sort_order          INT             NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT pmac_pkey PRIMARY KEY (id),
            CONSTRAINT pmac_tenant_code_uq UNIQUE (tenant_id, achievement_code),
            CONSTRAINT pmac_trigger_type_chk CHECK (
                trigger_type IN ('order_count', 'total_spent_fen', 'share_count', 'review_count')
            )
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pmac_tenant_active "
        "ON points_mall_achievement_configs (tenant_id, is_active)"
    )
    op.execute("ALTER TABLE points_mall_achievement_configs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS pmac_tenant_isolation "
        "ON points_mall_achievement_configs"
    )
    op.execute("""
        CREATE POLICY pmac_tenant_isolation
            ON points_mall_achievement_configs
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)

    # ── 3. products 表新增字段 ───────────────────────────────────
    op.execute("""
        ALTER TABLE points_mall_products
            ADD COLUMN IF NOT EXISTS category_id UUID,
            ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20) NOT NULL DEFAULT 'brand',
            ADD COLUMN IF NOT EXISTS scope_store_ids UUID[] DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE points_mall_products
            ADD CONSTRAINT pmp_scope_type_chk
            CHECK (scope_type IN ('brand', 'store', 'region'))
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pmp_category "
        "ON points_mall_products (tenant_id, category_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pmp_scope "
        "ON points_mall_products (tenant_id, scope_type)"
    )

    # ── 4. orders 表新增字段 ─────────────────────────────────────
    op.execute("""
        ALTER TABLE points_mall_orders
            ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS shipping_info JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ
    """)
    op.execute("""
        ALTER TABLE points_mall_orders
            ADD CONSTRAINT pmo_fulfillment_status_chk
            CHECK (fulfillment_status IN ('pending', 'shipped', 'delivered', 'returned'))
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pmo_expired "
        "ON points_mall_orders (tenant_id, expired_at) "
        "WHERE expired_at IS NOT NULL AND status = 'pending'"
    )


def downgrade() -> None:
    # orders 字段
    op.execute("ALTER TABLE points_mall_orders DROP CONSTRAINT IF EXISTS pmo_fulfillment_status_chk")
    op.execute("ALTER TABLE points_mall_orders DROP COLUMN IF EXISTS fulfillment_status")
    op.execute("ALTER TABLE points_mall_orders DROP COLUMN IF EXISTS shipping_info")
    op.execute("ALTER TABLE points_mall_orders DROP COLUMN IF EXISTS expired_at")

    # products 字段
    op.execute("ALTER TABLE points_mall_products DROP CONSTRAINT IF EXISTS pmp_scope_type_chk")
    op.execute("ALTER TABLE points_mall_products DROP COLUMN IF EXISTS category_id")
    op.execute("ALTER TABLE points_mall_products DROP COLUMN IF EXISTS scope_type")
    op.execute("ALTER TABLE points_mall_products DROP COLUMN IF EXISTS scope_store_ids")

    # 成就配置表
    op.execute("DROP TABLE IF EXISTS points_mall_achievement_configs CASCADE")

    # 分类表
    op.execute("DROP TABLE IF EXISTS points_mall_categories CASCADE")
