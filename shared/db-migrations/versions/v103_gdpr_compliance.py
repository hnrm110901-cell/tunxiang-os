"""v103: GDPR 合规模块 — 数据主体删除/被遗忘权/数据可携权

新建 1 张表：
  gdpr_requests — 数据主体权利请求（erasure/portability/restriction）

设计要点：
  - request_type: erasure（被遗忘权）/ portability（数据可携）/ restriction（限制处理）
  - status: pending → reviewing → executed / rejected
  - executed_deletion 时在 customers 表匿名化 PII，不物理删除（审计要求）
  - anonymization_log 记录具体匿名化了哪些字段
  - retention_days: 默认 30 天后物理删除已匿名的附属数据

Revision ID: v103
Revises: v102
Create Date: 2026-04-01
"""

from alembic import op

revision = "v103"
down_revision = "v102b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS gdpr_requests (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            customer_id         UUID         NOT NULL,
            request_type        VARCHAR(20)  NOT NULL
                                    CHECK (request_type IN ('erasure','portability','restriction')),
            status              VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending','reviewing','executed','rejected')),
            requested_by        VARCHAR(200),
            requested_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            reviewed_by         UUID,
            reviewed_at         TIMESTAMPTZ,
            executed_by         UUID,
            executed_at         TIMESTAMPTZ,
            rejection_reason    TEXT,
            anonymization_log   JSONB,
            export_data_url     TEXT,
            retention_days      INT          NOT NULL DEFAULT 30,
            note                TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE gdpr_requests ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY gdpr_requests_rls ON gdpr_requests
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gdpr_requests_customer
            ON gdpr_requests(tenant_id, customer_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gdpr_requests_pending
            ON gdpr_requests(tenant_id, status, created_at)
            WHERE status IN ('pending','reviewing')
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gdpr_requests CASCADE")
