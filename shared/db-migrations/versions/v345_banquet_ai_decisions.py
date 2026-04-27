"""v345 — AI宴会决策日志 + 需求预测

- banquet_ai_decisions: AI决策记录(报价/排产/营销)
- banquet_demand_forecasts: 需求预测(按月/按类型)

Revision: v345_banquet_ai_decisions
"""

from alembic import op

revision = "v345_banquet_ai_decisions"
down_revision = "v346_stored_value_settlement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_ai_decisions (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID,
            banquet_id          UUID,
            agent_type          VARCHAR(30)     NOT NULL,
            decision_type       VARCHAR(30)     NOT NULL,
            input_context_json  JSONB           NOT NULL DEFAULT '{}',
            recommendation_json JSONB           NOT NULL DEFAULT '{}',
            reasoning           TEXT,
            confidence          NUMERIC(3,2)    NOT NULL DEFAULT 0.00,
            accepted            BOOLEAN,
            accepted_at         TIMESTAMPTZ,
            operator_id         UUID,
            operator_feedback   TEXT,
            execution_ms        INT             NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_ai_decisions_pkey PRIMARY KEY (id),
            CONSTRAINT bad_agent_chk CHECK (agent_type IN ('pricing','operations','growth')),
            CONSTRAINT bad_type_chk CHECK (decision_type IN (
                'quote_pricing','menu_suggestion','capacity_optimization',
                'staff_suggestion','purchase_timing','demand_forecast',
                'reorder_reminder','referral_incentive','churn_alert'
            ))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bad_tenant   ON banquet_ai_decisions (tenant_id, agent_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bad_banquet  ON banquet_ai_decisions (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bad_created  ON banquet_ai_decisions (tenant_id, created_at DESC)")
    op.execute("ALTER TABLE banquet_ai_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_ai_decisions_tenant_isolation ON banquet_ai_decisions")
    op.execute("""
        CREATE POLICY banquet_ai_decisions_tenant_isolation ON banquet_ai_decisions
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_ai_decisions FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_demand_forecasts (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            forecast_month      VARCHAR(7)      NOT NULL,
            event_type          VARCHAR(30)     NOT NULL,
            predicted_count     INT             NOT NULL DEFAULT 0,
            predicted_revenue_fen INT           NOT NULL DEFAULT 0,
            actual_count        INT,
            actual_revenue_fen  INT,
            accuracy_pct        NUMERIC(5,2),
            factors_json        JSONB           NOT NULL DEFAULT '{}',
            model_version       VARCHAR(20)     NOT NULL DEFAULT 'v1',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_demand_forecasts_pkey PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bdf_unique
            ON banquet_demand_forecasts (tenant_id, store_id, forecast_month, event_type)
            WHERE is_deleted = FALSE
    """)
    op.execute("ALTER TABLE banquet_demand_forecasts ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_demand_forecasts_tenant_isolation ON banquet_demand_forecasts")
    op.execute("""
        CREATE POLICY banquet_demand_forecasts_tenant_isolation ON banquet_demand_forecasts
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_demand_forecasts FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_demand_forecasts CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_ai_decisions CASCADE")
