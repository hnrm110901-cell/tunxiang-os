"""v105: 新建 split_payments 表 — 部分付款/AA分摊结账

新建 1 张表：
  split_payments — 订单分摊付款记录（AA分摊/桌台各付）

设计要点：
  - (order_id) 索引加速按订单查询
  - (tenant_id) 索引加速 RLS 过滤
  - status CHECK: pending/paid/cancelled
  - payment_method CHECK: wechat/alipay/cash/credit/tab
  - amount_fen 存分值，规避浮点精度问题
  - RLS: NULLIF(app.tenant_id) 防 NULL 绕过

Revision ID: v105
Revises: v104
Create Date: 2026-04-02
"""

from alembic import op

revision = "v105"
down_revision = "v104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_payments (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            order_id        UUID         NOT NULL REFERENCES orders(id),
            split_no        SMALLINT     NOT NULL,
            total_splits    SMALLINT     NOT NULL,
            amount_fen      INTEGER      NOT NULL,
            payment_method  TEXT         NOT NULL
                                CHECK (payment_method IN ('wechat','alipay','cash','credit','tab')),
            member_id       UUID         REFERENCES customers(id),
            status          TEXT         NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','paid','cancelled')),
            paid_at         TIMESTAMPTZ,
            created_by      UUID,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE split_payments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY split_payments_tenant_isolation ON split_payments
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_payments_order_id
            ON split_payments(order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_payments_tenant
            ON split_payments(tenant_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS split_payments CASCADE")
