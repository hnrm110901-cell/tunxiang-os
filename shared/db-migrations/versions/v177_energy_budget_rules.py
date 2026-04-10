"""v177 — 能耗预算与告警规则表

创建：
  energy_budgets     — 门店月度能耗预算（tenant+store+year+month UNIQUE）
  energy_alert_rules — 门店能耗告警规则

字段说明（energy_budgets）：
  period_type    — 预算周期类型：monthly（当前仅支持月度）
  period_value   — 周期值，格式 "YYYY-MM"（如 "2026-04"）
  electricity_budget_kwh — 月度电量预算（kWh，numeric(12,3)）
  gas_budget_m3          — 月度燃气预算（m³，numeric(12,3)）
  water_budget_ton       — 月度用水预算（吨，numeric(12,3)）
  cost_budget_fen        — 月度总能耗成本预算（分，整数）

字段说明（energy_alert_rules）：
  metric          — 监控指标：electricity_kwh|gas_m3|water_ton|cost_fen|ratio
  threshold       — 阈值（绝对值或百分比，如 90.0 表示 90%）
  comparison      — 比较类型：absolute|budget_pct|yoy_pct
  alert_level     — 严重程度：info|warning|critical

Revision: v177
"""

from alembic import op

revision = "v177"
down_revision = "v176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── energy_budgets ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS energy_budgets (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            period_type             VARCHAR(16) NOT NULL DEFAULT 'monthly',
            -- monthly（当前支持月度周期）
            period_value            VARCHAR(7)  NOT NULL,
            -- 格式 "YYYY-MM"，如 "2026-04"
            electricity_budget_kwh  NUMERIC(12,3),
            gas_budget_m3           NUMERIC(12,3),
            water_budget_ton        NUMERIC(12,3),
            cost_budget_fen         BIGINT,
            -- 月度总能耗成本预算（分）
            is_active               BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_energy_budgets_tenant_store_period
                UNIQUE (tenant_id, store_id, period_type, period_value)
        )
    """)
    # 兼容修复：旧版表可能缺少新字段，逐一补齐
    op.execute("ALTER TABLE energy_budgets ADD COLUMN IF NOT EXISTS period_type VARCHAR(16) NOT NULL DEFAULT 'monthly'")
    op.execute("ALTER TABLE energy_budgets ADD COLUMN IF NOT EXISTS period_value VARCHAR(7)")
    op.execute("ALTER TABLE energy_budgets ADD COLUMN IF NOT EXISTS cost_budget_fen BIGINT")
    op.execute("ALTER TABLE energy_budgets ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE energy_budgets ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_energy_budgets_tenant_store "
        "ON energy_budgets (tenant_id, store_id) WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_energy_budgets_tenant_period "
        "ON energy_budgets (tenant_id) WHERE is_deleted = FALSE"
    )
    op.execute("ALTER TABLE energy_budgets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY energy_budgets_rls ON energy_budgets
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE energy_budgets FORCE ROW LEVEL SECURITY")

    # ── energy_alert_rules ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS energy_alert_rules (
            id           UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id    UUID        NOT NULL,
            store_id     UUID        NOT NULL,
            rule_name    VARCHAR(100) NOT NULL,
            metric       VARCHAR(32) NOT NULL,
            -- electricity_kwh | gas_m3 | water_ton | cost_fen | ratio
            threshold    NUMERIC(14,4) NOT NULL,
            comparison   VARCHAR(16) NOT NULL,
            -- absolute | budget_pct | yoy_pct
            alert_level  VARCHAR(16) NOT NULL DEFAULT 'warning',
            -- info | warning | critical
            is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted   BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    # 兼容修复：旧版表可能缺少新字段
    op.execute("ALTER TABLE energy_alert_rules ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE energy_alert_rules ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_energy_alert_rules_tenant_store "
        "ON energy_alert_rules (tenant_id, store_id) WHERE is_deleted = FALSE AND is_active = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_energy_alert_rules_tenant_metric "
        "ON energy_alert_rules (tenant_id, metric) WHERE is_deleted = FALSE"
    )
    op.execute("ALTER TABLE energy_alert_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY energy_alert_rules_rls ON energy_alert_rules
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE energy_alert_rules FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS energy_alert_rules")
    op.execute("DROP TABLE IF EXISTS energy_budgets")
