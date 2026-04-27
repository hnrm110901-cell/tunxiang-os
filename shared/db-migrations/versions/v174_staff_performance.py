"""v174 — 员工绩效记录（E7）

创建：
  staff_performance_records — 员工每日绩效快照（每员工每日一条）

Revision: v174
"""

from alembic import op

revision = "v174"
down_revision = "v173"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS staff_performance_records (
            id                    UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id             UUID        NOT NULL,
            store_id              UUID        NOT NULL,
            stat_date             DATE        NOT NULL,
            employee_id           UUID        NOT NULL,
            employee_name         VARCHAR(64) NOT NULL DEFAULT '',
            role                  VARCHAR(16) NOT NULL,
            -- cashier / chef / waiter / runner
            orders_handled        INTEGER     NOT NULL DEFAULT 0,
            revenue_generated_fen BIGINT      NOT NULL DEFAULT 0,
            dishes_completed      INTEGER     NOT NULL DEFAULT 0,
            tables_served         INTEGER     NOT NULL DEFAULT 0,
            avg_service_score     NUMERIC(4,2),
            base_commission_fen   BIGINT      NOT NULL DEFAULT 0,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted            BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, store_id, stat_date, employee_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_tenant_store_date "
        "ON staff_performance_records (tenant_id, store_id, stat_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_tenant_employee "
        "ON staff_performance_records (tenant_id, employee_id, stat_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_tenant_role ON staff_performance_records (tenant_id, role, stat_date DESC)"
    )
    op.execute("ALTER TABLE staff_performance_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY staff_performance_records_rls ON staff_performance_records
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE staff_performance_records FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staff_performance_records")
