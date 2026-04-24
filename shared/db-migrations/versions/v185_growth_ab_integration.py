"""v185 — 增长中枢V2.1（A/B测试集成 + 储值/宴席/渠道字段扩展）

变更：
  growth_journey_enrollments — 新增 ab_test_id, ab_variant 字段
  growth_journey_templates — 新增 ab_test_id 字段
  customer_growth_profiles — 新增 stored_value_balance_fen, last_banquet_at, primary_channel 字段

Revision: v185
"""

from alembic import op

revision = "v185"
down_revision = "v184"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── growth_journey_enrollments 扩展 ──
    op.execute("ALTER TABLE growth_journey_enrollments ADD COLUMN IF NOT EXISTS ab_test_id UUID")
    op.execute("ALTER TABLE growth_journey_enrollments ADD COLUMN IF NOT EXISTS ab_variant TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gje_ab_test "
        "ON growth_journey_enrollments (tenant_id, ab_test_id) "
        "WHERE ab_test_id IS NOT NULL"
    )

    # ── growth_journey_templates 扩展 ──
    op.execute("ALTER TABLE growth_journey_templates ADD COLUMN IF NOT EXISTS ab_test_id UUID")

    # ── customer_growth_profiles 扩展（储值/宴席/渠道） ──
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS stored_value_balance_fen BIGINT")
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS last_banquet_at TIMESTAMPTZ")
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS last_banquet_store_id UUID")
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS primary_channel TEXT")
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS channel_order_count INT DEFAULT 0")
    op.execute("ALTER TABLE customer_growth_profiles ADD COLUMN IF NOT EXISTS brand_order_count INT DEFAULT 0")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_stored_value "
        "ON customer_growth_profiles (tenant_id, stored_value_balance_fen) "
        "WHERE stored_value_balance_fen IS NOT NULL AND stored_value_balance_fen > 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_banquet "
        "ON customer_growth_profiles (tenant_id, last_banquet_at) "
        "WHERE last_banquet_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_channel "
        "ON customer_growth_profiles (tenant_id, primary_channel) "
        "WHERE primary_channel IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE growth_journey_enrollments DROP COLUMN IF EXISTS ab_test_id")
    op.execute("ALTER TABLE growth_journey_enrollments DROP COLUMN IF EXISTS ab_variant")
    op.execute("ALTER TABLE growth_journey_templates DROP COLUMN IF EXISTS ab_test_id")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS stored_value_balance_fen")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS last_banquet_at")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS last_banquet_store_id")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS primary_channel")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS channel_order_count")
    op.execute("ALTER TABLE customer_growth_profiles DROP COLUMN IF EXISTS brand_order_count")
