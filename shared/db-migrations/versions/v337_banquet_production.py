"""v337 — 宴会排产引擎 (Banquet Production)

排产计划 + 任务分配：
- banquet_production_plans: 排产主计划(出菜时序/人员需求)
- banquet_production_tasks: 排产任务(菜品/档口/厨师/状态机)

Revision: v337_banquet_production
"""

from alembic import op

revision = "v337_banquet_production"
down_revision = "v336_banquet_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_production_plans (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            banquet_id          UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            plan_date           DATE            NOT NULL,
            status              VARCHAR(20)     NOT NULL DEFAULT 'planned',
            total_dishes        INT             NOT NULL DEFAULT 0,
            total_servings      INT             NOT NULL DEFAULT 0,
            prep_start_time     TIME,
            service_start_time  TIME,
            course_timeline_json JSONB          NOT NULL DEFAULT '[]',
            staff_required_json JSONB           NOT NULL DEFAULT '{}',
            kitchen_notes       TEXT,
            confirmed_by        UUID,
            confirmed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_production_plans_pkey PRIMARY KEY (id),
            CONSTRAINT bpp_status_chk CHECK (
                status IN ('planned','confirmed','in_progress','completed','cancelled')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpp_banquet    ON banquet_production_plans (tenant_id, banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpp_store_date ON banquet_production_plans (tenant_id, store_id, plan_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpp_status     ON banquet_production_plans (tenant_id, status)")
    op.execute("ALTER TABLE banquet_production_plans ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_production_plans_tenant_isolation ON banquet_production_plans")
    op.execute("""
        CREATE POLICY banquet_production_plans_tenant_isolation ON banquet_production_plans
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_production_plans FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_production_tasks (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            plan_id             UUID            NOT NULL,
            course_no           INT             NOT NULL,
            course_name         VARCHAR(50),
            dish_id             UUID,
            dish_name           VARCHAR(100)    NOT NULL,
            quantity            INT             NOT NULL,
            prep_time_min       INT             NOT NULL DEFAULT 0,
            cook_time_min       INT             NOT NULL DEFAULT 0,
            station_id          UUID,
            station_name        VARCHAR(50),
            assigned_chef_id    UUID,
            assigned_chef_name  VARCHAR(50),
            status              VARCHAR(20)     NOT NULL DEFAULT 'pending',
            target_serve_time   TIME,
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            notes               VARCHAR(500),
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_production_tasks_pkey PRIMARY KEY (id),
            CONSTRAINT bpt_status_chk CHECK (
                status IN ('pending','prepping','cooking','plated','served','cancelled')
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpt_plan   ON banquet_production_tasks (tenant_id, plan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpt_status ON banquet_production_tasks (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bpt_chef   ON banquet_production_tasks (tenant_id, assigned_chef_id)")
    op.execute("ALTER TABLE banquet_production_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_production_tasks_tenant_isolation ON banquet_production_tasks")
    op.execute("""
        CREATE POLICY banquet_production_tasks_tenant_isolation ON banquet_production_tasks
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_production_tasks FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_production_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_production_plans CASCADE")
