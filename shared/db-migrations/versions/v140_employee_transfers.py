"""v140 — 员工调岗记录表 + role_configs 权限 JSON 列

变更：
  1. 新增 employee_transfers 表 — 员工门店调岗申请记录（pending/approved/rejected）
     RLS 策略采用 NULLIF + WITH CHECK + FORCE 标准写法。
  2. role_configs 表新增 permissions_json JSONB 列 — 存储 web-admin 权限管理页面使用的
     权限 key 数组（如 ["store:view","order:create"]），与数值型权限限制字段并存。

Revision ID: v140
Revises: v139
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v140"
down_revision = "v139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_transfers (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            employee_id     UUID         NOT NULL,
            from_store_id   UUID,
            to_store_id     UUID         NOT NULL,
            reason          TEXT,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected')),
            requested_by    UUID,
            approved_by     UUID,
            effective_date  DATE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)

    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE employee_transfers
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_transfers_tenant_employee
            ON employee_transfers (tenant_id, employee_id)
        WHERE is_deleted = FALSE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_transfers_tenant_status
            ON employee_transfers (tenant_id, status)
        WHERE is_deleted = FALSE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_transfers_to_store
            ON employee_transfers (tenant_id, to_store_id)
        WHERE is_deleted = FALSE
    """)

    # ── updated_at 自动触发器 ───────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_employee_transfers_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE TRIGGER trg_employee_transfers_updated_at
            BEFORE UPDATE ON employee_transfers
            FOR EACH ROW
            EXECUTE FUNCTION update_employee_transfers_updated_at()
    """)

    # ── RLS ────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE employee_transfers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_transfers FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS et_select ON employee_transfers;")
    op.execute("DROP POLICY IF EXISTS et_select ON employee_transfers;")
    op.execute("""
        CREATE POLICY et_select ON employee_transfers
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("DROP POLICY IF EXISTS et_insert ON employee_transfers;")
    op.execute("DROP POLICY IF EXISTS et_insert ON employee_transfers;")
    op.execute("""
        CREATE POLICY et_insert ON employee_transfers
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("DROP POLICY IF EXISTS et_update ON employee_transfers;")
    op.execute("DROP POLICY IF EXISTS et_update ON employee_transfers;")
    op.execute("""
        CREATE POLICY et_update ON employee_transfers
            FOR UPDATE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)


    # ── role_configs: 新增 permissions_json 列（web-admin 权限 key 数组） ────
    op.execute("""
        ALTER TABLE role_configs
            ADD COLUMN IF NOT EXISTS permissions_json JSONB DEFAULT '[]'::jsonb
    """)


def downgrade() -> None:
    # role_configs 权限列回滚
    op.execute("""
        ALTER TABLE role_configs DROP COLUMN IF EXISTS permissions_json
    """)

    op.execute("DROP POLICY IF EXISTS et_update ON employee_transfers")
    op.execute("DROP POLICY IF EXISTS et_insert ON employee_transfers")
    op.execute("DROP POLICY IF EXISTS et_select ON employee_transfers")
    op.execute("ALTER TABLE employee_transfers DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TRIGGER IF EXISTS trg_employee_transfers_updated_at ON employee_transfers")
    op.execute("DROP FUNCTION IF EXISTS update_employee_transfers_updated_at()")
    op.execute("DROP TABLE IF EXISTS employee_transfers")
