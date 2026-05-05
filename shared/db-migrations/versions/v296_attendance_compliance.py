"""v255: attendance_compliance_logs table

考勤深度合规检测记录表：GPS异常/同设备代打/加班超时/代打卡/位置不符。

Revision ID: v255
Revises: v254
Create Date: 2026-04-13
"""

from alembic import op

revision = "v296b"
down_revision = "v295"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── attendance_compliance_logs — 考勤合规违规记录表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attendance_compliance_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            employee_name   VARCHAR(100),
            store_id        UUID,
            check_date      DATE NOT NULL,
            violation_type  VARCHAR(30) NOT NULL,
            severity        VARCHAR(10) DEFAULT 'medium',
            detail          JSONB DEFAULT '{}'::jsonb,
            status          VARCHAR(20) DEFAULT 'pending',
            confirmed_by    UUID,
            confirmed_at    TIMESTAMPTZ,
            appeal_reason   TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── 索引 ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_att_compliance_tenant_date
            ON attendance_compliance_logs (tenant_id, check_date);
        CREATE INDEX IF NOT EXISTS idx_att_compliance_tenant_employee
            ON attendance_compliance_logs (tenant_id, employee_id);
        CREATE INDEX IF NOT EXISTS idx_att_compliance_tenant_type
            ON attendance_compliance_logs (tenant_id, violation_type);
        CREATE INDEX IF NOT EXISTS idx_att_compliance_tenant_status
            ON attendance_compliance_logs (tenant_id, status);
    """)

    # ── RLS ──────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE attendance_compliance_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS rls_attendance_compliance_logs ON attendance_compliance_logs;
        CREATE POLICY rls_attendance_compliance_logs ON attendance_compliance_logs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attendance_compliance_logs CASCADE;")
