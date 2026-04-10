"""v186 — 增长中枢V2.2（多品牌架构 + 门店维度联动）

变更：
  8张growth_*表 — 新增 brand_id 字段（可选，NULL表示集团级）
  growth_journey_enrollments — 新增 store_id 字段
  growth_touch_executions — 新增 store_id 字段
  growth_journey_templates — 新增 brand_scope 字段（all/specific）
  新建 growth_brand_configs — 品牌级增长配置表

Revision: v186
"""
from alembic import op

revision = "v186"
down_revision = "v185"
branch_labels = None
depends_on = None

_TABLES_NEED_BRAND = [
    "customer_growth_profiles",
    "growth_journey_templates",
    "growth_journey_template_steps",
    "growth_journey_enrollments",
    "growth_touch_templates",
    "growth_touch_executions",
    "growth_service_repair_cases",
    "growth_agent_strategy_suggestions",
]


def upgrade() -> None:
    # ── 所有growth表加brand_id ──
    for t in _TABLES_NEED_BRAND:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS brand_id UUID")

    # brand_id索引（截断表名避免标识符过长）
    for t in _TABLES_NEED_BRAND:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{t[:20]}_brand "
            f"ON {t} (tenant_id, brand_id) WHERE brand_id IS NOT NULL"
        )

    # ── enrollment加store_id ──
    op.execute("ALTER TABLE growth_journey_enrollments ADD COLUMN IF NOT EXISTS store_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gje_store "
        "ON growth_journey_enrollments (tenant_id, store_id) WHERE store_id IS NOT NULL"
    )

    # ── touch_executions加store_id ──
    op.execute("ALTER TABLE growth_touch_executions ADD COLUMN IF NOT EXISTS store_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtexec_store "
        "ON growth_touch_executions (tenant_id, store_id) WHERE store_id IS NOT NULL"
    )

    # ── journey_templates加brand_scope ──
    op.execute(
        "ALTER TABLE growth_journey_templates "
        "ADD COLUMN IF NOT EXISTS brand_scope TEXT DEFAULT 'all'"
    )
    op.execute(
        "ALTER TABLE growth_journey_templates "
        "ADD COLUMN IF NOT EXISTS allowed_brand_ids JSONB DEFAULT '[]'::jsonb"
    )

    # ── 新建品牌级增长配置表 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_brand_configs (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            brand_id        UUID        NOT NULL,
            brand_name      TEXT        NOT NULL,
            -- 增长策略配置
            growth_enabled  BOOLEAN     DEFAULT TRUE,
            daily_touch_budget INT      DEFAULT 100,
            monthly_offer_budget_fen BIGINT DEFAULT 1000000,
            max_touch_per_customer_day INT DEFAULT 2,
            max_touch_per_customer_week INT DEFAULT 5,
            -- 可用渠道
            enabled_channels JSONB      DEFAULT '["wecom","miniapp","sms"]'::jsonb,
            -- 可用旅程模板
            enabled_journey_types JSONB DEFAULT '["first_to_second","reactivation","service_repair","stored_value","banquet","channel_reflow"]'::jsonb,
            -- 自动化级别
            auto_approve_low_risk BOOLEAN DEFAULT FALSE,
            auto_approve_medium_risk BOOLEAN DEFAULT FALSE,
            -- 毛利保护
            margin_floor_pct INT        DEFAULT 30,
            -- 标准字段
            is_deleted      BOOLEAN     DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, brand_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gbc_tenant_brand "
        "ON growth_brand_configs (tenant_id, brand_id)"
    )

    # RLS
    op.execute("ALTER TABLE growth_brand_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_brand_configs FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS growth_brand_configs_tenant_isolation "
        "ON growth_brand_configs"
    )
    op.execute("""
        CREATE POLICY growth_brand_configs_tenant_isolation ON growth_brand_configs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS growth_brand_configs")

    for t in _TABLES_NEED_BRAND:
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS brand_id")

    op.execute("ALTER TABLE growth_journey_enrollments DROP COLUMN IF EXISTS store_id")
    op.execute("ALTER TABLE growth_touch_executions DROP COLUMN IF EXISTS store_id")
    op.execute("ALTER TABLE growth_journey_templates DROP COLUMN IF EXISTS brand_scope")
    op.execute("ALTER TABLE growth_journey_templates DROP COLUMN IF EXISTS allowed_brand_ids")
