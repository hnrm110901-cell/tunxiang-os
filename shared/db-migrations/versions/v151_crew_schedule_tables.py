"""v151 — 服务员排班相关表

新增表：
  crew_schedules        — 排班表（周级别，每人每日一条）
  crew_checkin_records  — 打卡记录（上班/下班，含 GPS + 设备信息）
  crew_shift_swaps      — 换班申请（含状态流转）
  crew_shift_summaries  — 交接班 AI 智能摘要

RLS 策略：标准安全模式（app.tenant_id，4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v151
Revises: v150
Create Date: 2026-04-04
"""
from alembic import op

revision = "v151"
down_revision = "v150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- ── 1. crew_schedules 排班表 ──────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS crew_schedules (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            crew_id         UUID        NOT NULL,
            schedule_date   DATE        NOT NULL,
            shift_name      VARCHAR(50) NOT NULL DEFAULT '',
            shift_start     TIME        DEFAULT NULL,
            shift_end       TIME        DEFAULT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_crew_schedules_tenant_crew_date
            ON crew_schedules (tenant_id, crew_id, schedule_date);
        CREATE INDEX IF NOT EXISTS idx_crew_schedules_tenant_store_date
            ON crew_schedules (tenant_id, store_id, schedule_date);

        ALTER TABLE crew_schedules ENABLE ROW LEVEL SECURITY;
        ALTER TABLE crew_schedules FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS crew_schedules_select ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_insert ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_update ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_delete ON crew_schedules;

        CREATE POLICY crew_schedules_select ON crew_schedules
            FOR SELECT USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_schedules_insert ON crew_schedules
            FOR INSERT WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_schedules_update ON crew_schedules
            FOR UPDATE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_schedules_delete ON crew_schedules
            FOR DELETE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );

        -- ── 2. crew_checkin_records 打卡记录表 ─────────────────────────────────
        CREATE TABLE IF NOT EXISTS crew_checkin_records (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            crew_id         UUID        NOT NULL,
            checkin_type    VARCHAR(20) NOT NULL,
            checkin_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            lat             DOUBLE PRECISION DEFAULT NULL,
            lng             DOUBLE PRECISION DEFAULT NULL,
            device_id       VARCHAR(200) DEFAULT NULL,
            in_window       BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_crew_checkin_tenant_crew_at
            ON crew_checkin_records (tenant_id, crew_id, checkin_at DESC);
        CREATE INDEX IF NOT EXISTS idx_crew_checkin_tenant_store_at
            ON crew_checkin_records (tenant_id, store_id, checkin_at DESC);

        ALTER TABLE crew_checkin_records ENABLE ROW LEVEL SECURITY;
        ALTER TABLE crew_checkin_records FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS crew_checkin_records_select ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_insert ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_update ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_delete ON crew_checkin_records;

        CREATE POLICY crew_checkin_records_select ON crew_checkin_records
            FOR SELECT USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_checkin_records_insert ON crew_checkin_records
            FOR INSERT WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_checkin_records_update ON crew_checkin_records
            FOR UPDATE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_checkin_records_delete ON crew_checkin_records
            FOR DELETE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );

        -- ── 3. crew_shift_swaps 换班申请表 ─────────────────────────────────────
        CREATE TABLE IF NOT EXISTS crew_shift_swaps (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            crew_id         UUID        NOT NULL,
            from_date       DATE        NOT NULL,
            to_crew_id      VARCHAR(200) NOT NULL,
            reason          TEXT        DEFAULT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            approved_by     VARCHAR(200) DEFAULT NULL,
            approved_at     TIMESTAMPTZ DEFAULT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_crew_shift_swaps_tenant_crew
            ON crew_shift_swaps (tenant_id, crew_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_crew_shift_swaps_tenant_status
            ON crew_shift_swaps (tenant_id, status);

        ALTER TABLE crew_shift_swaps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE crew_shift_swaps FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS crew_shift_swaps_select ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_insert ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_update ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_delete ON crew_shift_swaps;

        CREATE POLICY crew_shift_swaps_select ON crew_shift_swaps
            FOR SELECT USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_swaps_insert ON crew_shift_swaps
            FOR INSERT WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_swaps_update ON crew_shift_swaps
            FOR UPDATE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_swaps_delete ON crew_shift_swaps
            FOR DELETE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );

        -- ── 4. crew_shift_summaries 交接班摘要表 ──────────────────────────────
        CREATE TABLE IF NOT EXISTS crew_shift_summaries (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            crew_id         UUID        NOT NULL,
            shift_date      DATE        NOT NULL,
            shift_label     VARCHAR(50) NOT NULL DEFAULT '',
            summary         TEXT        NOT NULL DEFAULT '',
            table_count     INTEGER     NOT NULL DEFAULT 0,
            revenue_fen     BIGINT      NOT NULL DEFAULT 0,
            turnover_rate   NUMERIC(5,2) NOT NULL DEFAULT 0,
            satisfaction    INTEGER     DEFAULT NULL,
            pending_count   INTEGER     NOT NULL DEFAULT 0,
            complaint_count INTEGER     NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        CREATE INDEX IF NOT EXISTS idx_crew_shift_summaries_tenant_crew
            ON crew_shift_summaries (tenant_id, crew_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_crew_shift_summaries_tenant_store_date
            ON crew_shift_summaries (tenant_id, store_id, shift_date DESC);

        ALTER TABLE crew_shift_summaries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE crew_shift_summaries FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS crew_shift_summaries_select ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_insert ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_update ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_delete ON crew_shift_summaries;

        CREATE POLICY crew_shift_summaries_select ON crew_shift_summaries
            FOR SELECT USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_summaries_insert ON crew_shift_summaries
            FOR INSERT WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_summaries_update ON crew_shift_summaries
            FOR UPDATE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
        CREATE POLICY crew_shift_summaries_delete ON crew_shift_summaries
            FOR DELETE USING (
                tenant_id IS NOT NULL
                AND tenant_id::text = current_setting('app.tenant_id', true)
            );
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS crew_shift_summaries_delete ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_update ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_insert ON crew_shift_summaries;
        DROP POLICY IF EXISTS crew_shift_summaries_select ON crew_shift_summaries;
        DROP TABLE IF EXISTS crew_shift_summaries;

        DROP POLICY IF EXISTS crew_shift_swaps_delete ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_update ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_insert ON crew_shift_swaps;
        DROP POLICY IF EXISTS crew_shift_swaps_select ON crew_shift_swaps;
        DROP TABLE IF EXISTS crew_shift_swaps;

        DROP POLICY IF EXISTS crew_checkin_records_delete ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_update ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_insert ON crew_checkin_records;
        DROP POLICY IF EXISTS crew_checkin_records_select ON crew_checkin_records;
        DROP TABLE IF EXISTS crew_checkin_records;

        DROP POLICY IF EXISTS crew_schedules_delete ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_update ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_insert ON crew_schedules;
        DROP POLICY IF EXISTS crew_schedules_select ON crew_schedules;
        DROP TABLE IF EXISTS crew_schedules;
    """)
