"""v123 — 员工积分流水表（HR 积分 API 持久化）

供 tx-org ``employee_points_service`` 写入；与 ``employees`` 关联。

Revision ID: v123
Revises: v122
"""
from alembic import op

revision = "v123"
down_revision = "v122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_point_logs (
            id               UUID         PRIMARY KEY,
            tenant_id        UUID         NOT NULL,
            employee_id      UUID         NOT NULL
                REFERENCES employees(id),
            rule_code        VARCHAR(64)  NOT NULL,
            points           INT          NOT NULL,
            note             TEXT,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE employee_point_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY employee_point_logs_rls ON employee_point_logs
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_point_logs_tenant_emp
            ON employee_point_logs(tenant_id, employee_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_point_logs_tenant_rule
            ON employee_point_logs(tenant_id, rule_code)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS employee_point_logs CASCADE")
