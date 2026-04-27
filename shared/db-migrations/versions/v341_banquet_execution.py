"""v341 — 宴会执行SOP (Banquet Execution)

当日执行计划 + 执行日志：
- banquet_execution_plans: 执行计划(检查点/分工)
- banquet_execution_logs: 节点打卡日志

Revision: v341_banquet_execution
"""

from alembic import op

revision = "v341_banquet_execution"
down_revision = "v340_banquet_day_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_execution_plans (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            banquet_id          UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            sop_template_id     UUID,
            checkpoints_json    JSONB           NOT NULL DEFAULT '[]',
            assigned_staff_json JSONB           NOT NULL DEFAULT '{}',
            total_checkpoints   INT             NOT NULL DEFAULT 0,
            completed_checkpoints INT           NOT NULL DEFAULT 0,
            status              VARCHAR(20)     NOT NULL DEFAULT 'planned',
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_execution_plans_pkey PRIMARY KEY (id),
            CONSTRAINT bep_status_chk CHECK (status IN ('planned','executing','completed','cancelled'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bep_banquet ON banquet_execution_plans (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bep_store   ON banquet_execution_plans (tenant_id, store_id)")
    op.execute("ALTER TABLE banquet_execution_plans ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_execution_plans_tenant_isolation ON banquet_execution_plans")
    op.execute("""
        CREATE POLICY banquet_execution_plans_tenant_isolation ON banquet_execution_plans
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_execution_plans FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_execution_logs (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            plan_id             UUID            NOT NULL,
            checkpoint_index    INT             NOT NULL,
            checkpoint_name     VARCHAR(100)    NOT NULL,
            checkpoint_type     VARCHAR(30)     NOT NULL DEFAULT 'task',
            scheduled_time      TIME,
            actual_time         TIMESTAMPTZ,
            delay_min           INT             NOT NULL DEFAULT 0,
            executor_id         UUID,
            executor_name       VARCHAR(100),
            status              VARCHAR(20)     NOT NULL DEFAULT 'pending',
            issue_note          TEXT,
            photos_json         JSONB           NOT NULL DEFAULT '[]',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_execution_logs_pkey PRIMARY KEY (id),
            CONSTRAINT bel_status_chk CHECK (status IN ('pending','in_progress','completed','skipped','escalated'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bel_plan ON banquet_execution_logs (tenant_id, plan_id)")
    op.execute("ALTER TABLE banquet_execution_logs ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_execution_logs_tenant_isolation ON banquet_execution_logs")
    op.execute("""
        CREATE POLICY banquet_execution_logs_tenant_isolation ON banquet_execution_logs
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_execution_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_execution_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_execution_plans CASCADE")
