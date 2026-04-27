"""v340 — 宴会日调度 (Banquet Day Schedule)

当日宴会统筹编排：
- banquet_day_schedules: 聚合当日所有宴会(场地/人员/厨房/时间轴)

Revision: v340_banquet_day_schedule
"""

from alembic import op

revision = "v340_banquet_day_schedule"
down_revision = "v339_kitchen_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_day_schedules (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            store_id                UUID            NOT NULL,
            schedule_date           DATE            NOT NULL,
            banquet_ids             JSONB           NOT NULL DEFAULT '[]',
            banquet_count           INT             NOT NULL DEFAULT 0,
            total_guests            INT             NOT NULL DEFAULT 0,
            total_tables            INT             NOT NULL DEFAULT 0,
            venue_allocation_json   JSONB           NOT NULL DEFAULT '{}',
            staff_allocation_json   JSONB           NOT NULL DEFAULT '{}',
            timeline_json           JSONB           NOT NULL DEFAULT '[]',
            kitchen_load_json       JSONB           NOT NULL DEFAULT '{}',
            status                  VARCHAR(20)     NOT NULL DEFAULT 'planned',
            confirmed_by            UUID,
            confirmed_at            TIMESTAMPTZ,
            notes                   TEXT,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_day_schedules_pkey PRIMARY KEY (id),
            CONSTRAINT bds_status_chk CHECK (status IN ('planned','confirmed','executing','completed'))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bds_unique
            ON banquet_day_schedules (tenant_id, store_id, schedule_date)
            WHERE is_deleted = FALSE
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bds_store_date ON banquet_day_schedules (tenant_id, store_id, schedule_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bds_status     ON banquet_day_schedules (tenant_id, status)")
    op.execute("ALTER TABLE banquet_day_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_day_schedules_tenant_isolation ON banquet_day_schedules")
    op.execute("""
        CREATE POLICY banquet_day_schedules_tenant_isolation ON banquet_day_schedules
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_day_schedules FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_day_schedules CASCADE")
