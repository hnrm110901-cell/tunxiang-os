"""v150 — 经理端折扣审批申请表 + KPI 快照表

新增：
  manager_discount_requests — 服务员发起的折扣/优惠申请（经理端审批）

Revision ID: v150
Revises: v149
Create Date: 2026-04-04
"""

from alembic import op

revision = "v150"
down_revision = "v148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS manager_discount_requests (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            applicant_id    VARCHAR(100) NOT NULL DEFAULT '',
            applicant       VARCHAR(100) NOT NULL,
            applicant_role  VARCHAR(50)  NOT NULL DEFAULT '',
            table_label     VARCHAR(50)  NOT NULL DEFAULT '',
            discount_type   VARCHAR(100) NOT NULL,
            discount_amount INTEGER      NOT NULL DEFAULT 0,
            reason          TEXT,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
            manager_reason  TEXT,
            approved_by     VARCHAR(100),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT chk_mdr_status
                CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'))
        );

        COMMENT ON TABLE manager_discount_requests IS
            '经理端折扣审批申请：服务员在 POS 发起折扣/赠品申请，经理 App 审批';

        CREATE INDEX IF NOT EXISTS ix_mdr_tenant_store
            ON manager_discount_requests (tenant_id, store_id);
        CREATE INDEX IF NOT EXISTS ix_mdr_status
            ON manager_discount_requests (tenant_id, store_id, status)
            WHERE is_deleted = FALSE;
        CREATE INDEX IF NOT EXISTS ix_mdr_created
            ON manager_discount_requests (created_at DESC);

        -- RLS
        ALTER TABLE manager_discount_requests ENABLE ROW LEVEL SECURITY;
        ALTER TABLE manager_discount_requests FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS mdr_tenant_isolation ON manager_discount_requests;
        CREATE POLICY mdr_tenant_isolation ON manager_discount_requests
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

        DROP POLICY IF EXISTS mdr_null_guard ON manager_discount_requests;
        CREATE POLICY mdr_null_guard ON manager_discount_requests
            AS RESTRICTIVE
            USING (current_setting('app.tenant_id', true) IS NOT NULL
                   AND current_setting('app.tenant_id', true) <> '');
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS mdr_null_guard ON manager_discount_requests;
        DROP POLICY IF EXISTS mdr_tenant_isolation ON manager_discount_requests;
        DROP TABLE IF EXISTS manager_discount_requests;
    """)
