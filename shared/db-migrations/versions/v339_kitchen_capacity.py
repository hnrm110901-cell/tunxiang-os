"""v339 — 厨房产能管理 (Kitchen Capacity)

产能时段 + 冲突检测：
- kitchen_capacity_slots: 厨房产能时段表(按天/时段)
- banquet_capacity_conflicts: 产能冲突记录

Revision: v339_kitchen_capacity
"""

from alembic import op

revision = "v339_kitchen_capacity"
down_revision = "v338_banquet_materials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS kitchen_capacity_slots (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            store_id                UUID            NOT NULL,
            slot_date               DATE            NOT NULL,
            time_slot               VARCHAR(20)     NOT NULL,
            start_time              TIME            NOT NULL,
            end_time                TIME            NOT NULL,
            max_dishes_per_hour     INT             NOT NULL DEFAULT 100,
            max_concurrent_banquets INT             NOT NULL DEFAULT 2,
            current_load_dishes     INT             NOT NULL DEFAULT 0,
            current_banquet_count   INT             NOT NULL DEFAULT 0,
            available_capacity_dishes INT           NOT NULL DEFAULT 100,
            staff_on_duty_json      JSONB           NOT NULL DEFAULT '{}',
            is_blocked              BOOLEAN         NOT NULL DEFAULT FALSE,
            block_reason            VARCHAR(200),
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT kitchen_capacity_slots_pkey PRIMARY KEY (id),
            CONSTRAINT kcs_time_slot_chk CHECK (
                time_slot IN ('morning','lunch_prep','lunch_service','afternoon','dinner_prep','dinner_service','late_night')
            )
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_kcs_unique
            ON kitchen_capacity_slots (tenant_id, store_id, slot_date, time_slot)
            WHERE is_deleted = FALSE
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_kcs_store_date ON kitchen_capacity_slots (tenant_id, store_id, slot_date)")
    op.execute("ALTER TABLE kitchen_capacity_slots ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS kitchen_capacity_slots_tenant_isolation ON kitchen_capacity_slots")
    op.execute("""
        CREATE POLICY kitchen_capacity_slots_tenant_isolation ON kitchen_capacity_slots
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE kitchen_capacity_slots FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_capacity_conflicts (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            conflict_date       DATE            NOT NULL,
            time_slot           VARCHAR(20)     NOT NULL,
            conflict_type       VARCHAR(30)     NOT NULL,
            severity            VARCHAR(10)     NOT NULL,
            description         TEXT            NOT NULL,
            affected_banquet_ids JSONB          NOT NULL DEFAULT '[]',
            resolution          TEXT,
            resolved_by         UUID,
            resolved_at         TIMESTAMPTZ,
            status              VARCHAR(20)     NOT NULL DEFAULT 'open',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_capacity_conflicts_pkey PRIMARY KEY (id),
            CONSTRAINT bcc_type_chk CHECK (
                conflict_type IN ('dish_overload','banquet_overload','staff_shortage','ingredient_shortage','equipment_conflict')
            ),
            CONSTRAINT bcc_severity_chk CHECK (severity IN ('info','warning','critical')),
            CONSTRAINT bcc_status_chk CHECK (status IN ('open','acknowledged','resolved','escalated'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bcc_store_date ON banquet_capacity_conflicts (tenant_id, store_id, conflict_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bcc_status     ON banquet_capacity_conflicts (tenant_id, status)")
    op.execute("ALTER TABLE banquet_capacity_conflicts ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_capacity_conflicts_tenant_isolation ON banquet_capacity_conflicts")
    op.execute("""
        CREATE POLICY banquet_capacity_conflicts_tenant_isolation ON banquet_capacity_conflicts
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_capacity_conflicts FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_capacity_conflicts CASCADE")
    op.execute("DROP TABLE IF EXISTS kitchen_capacity_slots CASCADE")
