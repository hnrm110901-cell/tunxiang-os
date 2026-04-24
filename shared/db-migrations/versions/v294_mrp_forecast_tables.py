"""v283 — MRP智能预估：生产计划+采购计划联动

对标天财商龙SCM"精益管理"的MRP智能预估+按计划领料功能。

五张表：
  1. mrp_forecast_plans — MRP预估计划（需求驱动/手动/混合）
  2. mrp_demand_lines — 需求行（BOM展开后的原料净需求）
  3. mrp_production_suggestions — 生产建议（自制半成品）
  4. mrp_procurement_suggestions — 采购建议（外购原料）
  5. mrp_planned_issues — 按计划领料（生产建议→领料单）

Revision ID: v294_mrp_forecast
Revises: v293
Create Date: 2026-04-24
"""
from alembic import op

revision = "v294_mrp_forecast"
down_revision = "v293"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. mrp_forecast_plans ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS mrp_forecast_plans (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            plan_name           VARCHAR(200) NOT NULL,
            plan_type           VARCHAR(30) NOT NULL DEFAULT 'demand_driven'
                                CHECK (plan_type IN ('demand_driven', 'manual', 'hybrid')),
            status              VARCHAR(30) NOT NULL DEFAULT 'draft'
                                CHECK (status IN (
                                    'draft', 'calculating', 'calculated',
                                    'approved', 'executing', 'completed'
                                )),
            forecast_date_from  DATE NOT NULL,
            forecast_date_to    DATE NOT NULL,
            parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by          UUID NOT NULL,
            approved_by         UUID,
            approved_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT chk_mrp_plan_date_range CHECK (forecast_date_to >= forecast_date_from)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_forecast_plans_tenant_status
            ON mrp_forecast_plans (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_forecast_plans_store
            ON mrp_forecast_plans (tenant_id, store_id, created_at DESC)
            WHERE is_deleted = false AND store_id IS NOT NULL
    """)

    op.execute("ALTER TABLE mrp_forecast_plans ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mrp_forecast_plans_tenant_isolation ON mrp_forecast_plans;
        CREATE POLICY mrp_forecast_plans_tenant_isolation ON mrp_forecast_plans
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. mrp_demand_lines ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS mrp_demand_lines (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            plan_id             UUID NOT NULL REFERENCES mrp_forecast_plans(id),
            ingredient_id       UUID NOT NULL,
            ingredient_name     VARCHAR(200) NOT NULL,
            unit                VARCHAR(30) NOT NULL DEFAULT '',
            forecast_demand_qty NUMERIC(12,3) NOT NULL DEFAULT 0,
            safety_stock_qty    NUMERIC(12,3) NOT NULL DEFAULT 0,
            current_stock_qty   NUMERIC(12,3) NOT NULL DEFAULT 0,
            in_transit_qty      NUMERIC(12,3) NOT NULL DEFAULT 0,
            net_requirement_qty NUMERIC(12,3) NOT NULL DEFAULT 0,
            source              VARCHAR(30) NOT NULL DEFAULT 'sales_forecast'
                                CHECK (source IN ('sales_forecast', 'manual', 'bom_explosion')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_demand_lines_plan
            ON mrp_demand_lines (plan_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_demand_lines_ingredient
            ON mrp_demand_lines (tenant_id, ingredient_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE mrp_demand_lines ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mrp_demand_lines_tenant_isolation ON mrp_demand_lines;
        CREATE POLICY mrp_demand_lines_tenant_isolation ON mrp_demand_lines
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. mrp_production_suggestions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS mrp_production_suggestions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            plan_id             UUID NOT NULL REFERENCES mrp_forecast_plans(id),
            product_id          UUID NOT NULL,
            product_name        VARCHAR(200) NOT NULL,
            suggested_qty       NUMERIC(12,3) NOT NULL DEFAULT 0
                                CHECK (suggested_qty >= 0),
            unit                VARCHAR(30) NOT NULL DEFAULT '',
            bom_id              UUID,
            required_date       DATE NOT NULL,
            priority            VARCHAR(20) NOT NULL DEFAULT 'medium'
                                CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
            status              VARCHAR(20) NOT NULL DEFAULT 'suggested'
                                CHECK (status IN (
                                    'suggested', 'approved', 'scheduled',
                                    'completed', 'cancelled'
                                )),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_prod_suggestions_plan
            ON mrp_production_suggestions (plan_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_prod_suggestions_date
            ON mrp_production_suggestions (tenant_id, required_date, priority)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE mrp_production_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mrp_prod_suggestions_tenant_isolation ON mrp_production_suggestions;
        CREATE POLICY mrp_prod_suggestions_tenant_isolation ON mrp_production_suggestions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. mrp_procurement_suggestions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS mrp_procurement_suggestions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            plan_id             UUID NOT NULL REFERENCES mrp_forecast_plans(id),
            ingredient_id       UUID NOT NULL,
            ingredient_name     VARCHAR(200) NOT NULL,
            suggested_qty       NUMERIC(12,3) NOT NULL DEFAULT 0
                                CHECK (suggested_qty >= 0),
            unit                VARCHAR(30) NOT NULL DEFAULT '',
            supplier_id         UUID,
            supplier_name       VARCHAR(200),
            estimated_cost_fen  BIGINT NOT NULL DEFAULT 0
                                CHECK (estimated_cost_fen >= 0),
            required_date       DATE NOT NULL,
            lead_time_days      INTEGER NOT NULL DEFAULT 1
                                CHECK (lead_time_days >= 0),
            status              VARCHAR(20) NOT NULL DEFAULT 'suggested'
                                CHECK (status IN (
                                    'suggested', 'approved', 'ordered',
                                    'received', 'cancelled'
                                )),
            purchase_order_id   UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_proc_suggestions_plan
            ON mrp_procurement_suggestions (plan_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_proc_suggestions_supplier
            ON mrp_procurement_suggestions (tenant_id, supplier_id, required_date)
            WHERE is_deleted = false AND supplier_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_proc_suggestions_date
            ON mrp_procurement_suggestions (tenant_id, required_date)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE mrp_procurement_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mrp_proc_suggestions_tenant_isolation ON mrp_procurement_suggestions;
        CREATE POLICY mrp_proc_suggestions_tenant_isolation ON mrp_procurement_suggestions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 5. mrp_planned_issues ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS mrp_planned_issues (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            production_suggestion_id    UUID NOT NULL REFERENCES mrp_production_suggestions(id),
            ingredient_id               UUID NOT NULL,
            ingredient_name             VARCHAR(200) NOT NULL,
            planned_qty                 NUMERIC(12,3) NOT NULL DEFAULT 0
                                        CHECK (planned_qty >= 0),
            actual_qty                  NUMERIC(12,3),
            unit                        VARCHAR(30) NOT NULL DEFAULT '',
            issued_at                   TIMESTAMPTZ,
            issued_by                   UUID,
            status                      VARCHAR(20) NOT NULL DEFAULT 'planned'
                                        CHECK (status IN (
                                            'planned', 'issued', 'partial', 'cancelled'
                                        )),
            variance_qty                NUMERIC(12,3),
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_planned_issues_prod
            ON mrp_planned_issues (production_suggestion_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrp_planned_issues_ingredient
            ON mrp_planned_issues (tenant_id, ingredient_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE mrp_planned_issues ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mrp_planned_issues_tenant_isolation ON mrp_planned_issues;
        CREATE POLICY mrp_planned_issues_tenant_isolation ON mrp_planned_issues
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mrp_planned_issues CASCADE")
    op.execute("DROP TABLE IF EXISTS mrp_procurement_suggestions CASCADE")
    op.execute("DROP TABLE IF EXISTS mrp_production_suggestions CASCADE")
    op.execute("DROP TABLE IF EXISTS mrp_demand_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS mrp_forecast_plans CASCADE")
