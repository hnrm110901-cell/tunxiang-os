"""v098 — operation_plans 表：高风险操作 Plan Mode

记录所有触发 Plan Mode 的操作请求，包括影响分析和确认状态。

Revision ID: v098
Revises: v097
Create Date: 2026-04-01
"""

from alembic import op

revision = "v098"
down_revision = "v097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS operation_plans (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            operation_type   VARCHAR(100) NOT NULL,
            operation_params JSONB        NOT NULL DEFAULT '{}',
            impact_analysis  JSONB        NOT NULL DEFAULT '{}',
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending_confirm',
            risk_level       VARCHAR(20)  NOT NULL DEFAULT 'medium',
            operator_id      UUID         NOT NULL,
            confirmed_by     UUID,
            confirmed_at     TIMESTAMPTZ,
            executed_at      TIMESTAMPTZ,
            expires_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)

    # RLS — 与其他表保持一致，使用 NULLIF 防止 NULL 绕过
    op.execute("ALTER TABLE operation_plans ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY operation_plans_rls ON operation_plans
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_operation_plans_tenant_status
            ON operation_plans(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_operation_plans_operator
            ON operation_plans(operator_id)
            WHERE is_deleted = false
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operation_plans CASCADE")
