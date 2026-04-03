"""v055 — 巡台签到日志

新增表：
  patrol_logs — 服务员BLE自动巡台记录

索引：
  (tenant_id, crew_id, checked_at)
  (tenant_id, table_no, checked_at)

RLS 策略：标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v055
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v055"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_logs (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            crew_id         UUID        NOT NULL,
            table_no        VARCHAR(50) NOT NULL,
            beacon_id       VARCHAR(200) DEFAULT NULL,
            signal_strength INTEGER      DEFAULT NULL,
            checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_patrol_logs_tenant_crew_checked
            ON patrol_logs (tenant_id, crew_id, checked_at DESC);

        CREATE INDEX IF NOT EXISTS idx_patrol_logs_tenant_table_checked
            ON patrol_logs (tenant_id, table_no, checked_at DESC);

        ALTER TABLE patrol_logs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE patrol_logs FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS patrol_logs_select ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_insert ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_update ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_delete ON patrol_logs;

        CREATE POLICY patrol_logs_select ON patrol_logs
            FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY patrol_logs_insert ON patrol_logs
            FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY patrol_logs_update ON patrol_logs
            FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );

        CREATE POLICY patrol_logs_delete ON patrol_logs
            FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            );
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS patrol_logs_delete ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_update ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_insert ON patrol_logs;
        DROP POLICY IF EXISTS patrol_logs_select ON patrol_logs;

        DROP TABLE IF EXISTS patrol_logs;
    """)
