"""v180 — 统一排班三表（shift_templates / unified_schedules / shift_gaps）

创建：
  shift_templates    — 班次模板（早班/中班/晚班等）
  unified_schedules  — 统一排班记录（员工+门店+日期+时段）
  shift_gaps         — 排班缺口（待认领的空缺班次）

Revision: v180
"""

from alembic import op

revision = "v180"
down_revision = "v179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── shift_templates ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS shift_templates (
            id                    UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id             UUID        NOT NULL,
            name                  TEXT        NOT NULL,
            start_time            TIME        NOT NULL,
            end_time              TIME        NOT NULL,
            break_minutes         INT         DEFAULT 0,
            color                 TEXT,
            applicable_positions  JSONB       DEFAULT '[]'::jsonb,
            is_active             BOOLEAN     DEFAULT TRUE,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_shift_templates_tenant "
        "ON shift_templates (tenant_id)"
    )
    op.execute("ALTER TABLE shift_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE shift_templates FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS shift_templates_tenant_isolation ON shift_templates")
    op.execute("""
        CREATE POLICY shift_templates_tenant_isolation ON shift_templates
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── unified_schedules ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS unified_schedules (
            id                UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            employee_id       UUID        NOT NULL,
            schedule_date     DATE        NOT NULL,
            shift_template_id UUID,
            start_time        TIME        NOT NULL,
            end_time          TIME        NOT NULL,
            break_minutes     INT         DEFAULT 0,
            position          TEXT,
            status            TEXT        DEFAULT 'scheduled',
            source            TEXT        DEFAULT 'manual',
            swap_from_id      UUID,
            notes             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, employee_id, schedule_date, start_time)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_unified_schedules_tenant_store_date "
        "ON unified_schedules (tenant_id, store_id, schedule_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_unified_schedules_tenant_employee_date "
        "ON unified_schedules (tenant_id, employee_id, schedule_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_unified_schedules_status "
        "ON unified_schedules (status)"
    )
    op.execute("ALTER TABLE unified_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE unified_schedules FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS unified_schedules_tenant_isolation ON unified_schedules")
    op.execute("""
        CREATE POLICY unified_schedules_tenant_isolation ON unified_schedules
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── shift_gaps ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS shift_gaps (
            id                UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            schedule_date     DATE        NOT NULL,
            position          TEXT        NOT NULL,
            shift_template_id UUID,
            urgency           TEXT        DEFAULT 'normal',
            status            TEXT        DEFAULT 'open',
            claimed_by        UUID,
            filled_at         TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_shift_gaps_tenant_store_date "
        "ON shift_gaps (tenant_id, store_id, schedule_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_shift_gaps_status "
        "ON shift_gaps (status)"
    )
    op.execute("ALTER TABLE shift_gaps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE shift_gaps FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS shift_gaps_tenant_isolation ON shift_gaps")
    op.execute("""
        CREATE POLICY shift_gaps_tenant_isolation ON shift_gaps
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shift_gaps")
    op.execute("DROP TABLE IF EXISTS unified_schedules")
    op.execute("DROP TABLE IF EXISTS shift_templates")
