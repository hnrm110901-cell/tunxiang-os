"""v346 — 宴会经营看板 (KPI + Benchmarks)

- banquet_kpi_snapshots: KPI快照(日/周/月)
- banquet_competitive_benchmarks: 跨店对标

Revision: v346_banquet_kpi
"""

from alembic import op

revision = "v346_banquet_kpi"
down_revision = "v345_banquet_ai_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_kpi_snapshots (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            store_id                UUID            NOT NULL,
            period                  VARCHAR(10)     NOT NULL,
            period_date             DATE            NOT NULL,
            leads_count             INT             NOT NULL DEFAULT 0,
            conversion_rate         NUMERIC(5,2)    NOT NULL DEFAULT 0,
            bookings_count          INT             NOT NULL DEFAULT 0,
            revenue_fen             INT             NOT NULL DEFAULT 0,
            avg_per_table_fen       INT             NOT NULL DEFAULT 0,
            avg_guest_count         INT             NOT NULL DEFAULT 0,
            top_event_type          VARCHAR(30),
            venue_utilization_rate  NUMERIC(5,2)    NOT NULL DEFAULT 0,
            customer_satisfaction   NUMERIC(3,1)    NOT NULL DEFAULT 0,
            repeat_rate             NUMERIC(5,2)    NOT NULL DEFAULT 0,
            total_tables            INT             NOT NULL DEFAULT 0,
            total_guests            INT             NOT NULL DEFAULT 0,
            cancellation_rate       NUMERIC(5,2)    NOT NULL DEFAULT 0,
            avg_lead_to_book_days   INT             NOT NULL DEFAULT 0,
            food_cost_rate          NUMERIC(5,2)    NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_kpi_snapshots_pkey PRIMARY KEY (id),
            CONSTRAINT bks_period_chk CHECK (period IN ('daily','weekly','monthly'))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bks_unique
            ON banquet_kpi_snapshots (tenant_id, store_id, period, period_date)
            WHERE is_deleted = FALSE
    """)
    op.execute("ALTER TABLE banquet_kpi_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_kpi_snapshots_tenant_isolation ON banquet_kpi_snapshots")
    op.execute("""
        CREATE POLICY banquet_kpi_snapshots_tenant_isolation ON banquet_kpi_snapshots
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_kpi_snapshots FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_competitive_benchmarks (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            period              VARCHAR(10)     NOT NULL,
            period_date         DATE            NOT NULL,
            metric_name         VARCHAR(50)     NOT NULL,
            store_value         NUMERIC(12,2)   NOT NULL DEFAULT 0,
            brand_avg           NUMERIC(12,2)   NOT NULL DEFAULT 0,
            brand_best          NUMERIC(12,2)   NOT NULL DEFAULT 0,
            rank                INT             NOT NULL DEFAULT 0,
            percentile          NUMERIC(5,2)    NOT NULL DEFAULT 0,
            trend               VARCHAR(10)     NOT NULL DEFAULT 'flat',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_competitive_benchmarks_pkey PRIMARY KEY (id),
            CONSTRAINT bcb_trend_chk CHECK (trend IN ('up','down','flat'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bcb_store ON banquet_competitive_benchmarks (tenant_id, store_id, period_date)")
    op.execute("ALTER TABLE banquet_competitive_benchmarks ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_competitive_benchmarks_tenant_isolation ON banquet_competitive_benchmarks")
    op.execute("""
        CREATE POLICY banquet_competitive_benchmarks_tenant_isolation ON banquet_competitive_benchmarks
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_competitive_benchmarks FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_competitive_benchmarks CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_kpi_snapshots CASCADE")
