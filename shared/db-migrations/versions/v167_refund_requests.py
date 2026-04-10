"""v167: 退款申请表 — refund_requests

字段设计：
  - id UUID PK
  - tenant_id UUID NOT NULL（RLS隔离）
  - order_id UUID NOT NULL（关联orders表，不加FK约束避免跨服务问题）
  - refund_type VARCHAR(20) CHECK ('full', 'partial')
  - refund_amount_fen BIGINT NOT NULL（退款金额，分）
  - reasons JSONB NOT NULL DEFAULT '[]'（退款原因列表）
  - description TEXT DEFAULT ''
  - items JSONB NOT NULL DEFAULT '[]'（退款商品明细）
  - image_urls JSONB NOT NULL DEFAULT '[]'（凭证图片）
  - status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK ('pending', 'approved', 'rejected', 'refunded')
  - reviewed_by UUID（审核人）
  - reviewed_at TIMESTAMPTZ
  - review_note TEXT DEFAULT ''
  - created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  - updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()

RLS：使用标准 NULLIF(current_setting('app.tenant_id', true), '')::UUID 模式

Revision ID: v167
Revises: v166
"""

from alembic import op

revision = "v167"
down_revision = "v166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS refund_requests (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            order_id            UUID        NOT NULL,
            refund_type         VARCHAR(20) NOT NULL DEFAULT 'full'
                                    CHECK (refund_type IN ('full', 'partial')),
            refund_amount_fen   BIGINT      NOT NULL,
            reasons             JSONB       NOT NULL DEFAULT '[]',
            description         TEXT        NOT NULL DEFAULT '',
            items               JSONB       NOT NULL DEFAULT '[]',
            image_urls          JSONB       NOT NULL DEFAULT '[]',
            status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'approved', 'rejected', 'refunded')),
            reviewed_by         UUID,
            reviewed_at         TIMESTAMPTZ,
            review_note         TEXT        NOT NULL DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_refund_requests_tenant
            ON refund_requests (tenant_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_refund_requests_order
            ON refund_requests (order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_refund_requests_status
            ON refund_requests (tenant_id, status)
    """)
    op.execute("ALTER TABLE refund_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'refund_requests' AND policyname = 'tenant_isolation'
          ) THEN
            CREATE POLICY tenant_isolation ON refund_requests
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
          END IF;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refund_requests CASCADE")
