"""v051 — 按座位点单与分账

新增字段（orders）：
  seat_count — 座位数，NULL 表示不启用座位模式

新增字段（order_items）：
  seat_no    — 归属座位号（1-based），NULL 表示全桌共享
  seat_label — 显示名称，例如 "3号" 或 "小明"

新建表：
  order_seats — 座位管理（每个座位的小计/已付/支付状态）

RLS 策略：
  order_seats 使用 v006+ 标准安全模式

Revision ID: v051
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v051"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. orders 新增字段：座位数
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS seat_count INTEGER DEFAULT NULL;

        COMMENT ON COLUMN orders.seat_count IS '座位数（NULL=不启用座位模式，1-20=启用）';
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. order_items 新增字段：座位归属
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE order_items
            ADD COLUMN IF NOT EXISTS seat_no    INTEGER      DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS seat_label VARCHAR(50)  DEFAULT NULL;

        COMMENT ON COLUMN order_items.seat_no    IS '归属座位号（1-based），NULL 表示全桌共享';
        COMMENT ON COLUMN order_items.seat_label IS '显示名称，例如 "3号" 或顾客姓名';
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. order_seats — 座位管理表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_seats (
            id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID         NOT NULL,
            order_id       UUID         NOT NULL,
            seat_no        INTEGER      NOT NULL,
            seat_label     VARCHAR(50),
            sub_total      NUMERIC(12,2) NOT NULL DEFAULT 0,
            paid_amount    NUMERIC(12,2) NOT NULL DEFAULT 0,
            payment_status VARCHAR(20)  NOT NULL DEFAULT 'unpaid'
                CHECK (payment_status IN ('unpaid', 'paying', 'paid')),
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted     BOOLEAN      NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_order_seats_order_seat
                UNIQUE (order_id, seat_no)
        );

        COMMENT ON TABLE order_seats IS
            '订单座位管理：每个座位的分账小计、已付金额和支付状态';

        CREATE INDEX IF NOT EXISTS ix_order_seats_tenant_order
            ON order_seats (tenant_id, order_id)
            WHERE is_deleted = FALSE;
    """)

    # RLS: order_seats
    op.execute("""
        ALTER TABLE order_seats ENABLE ROW LEVEL SECURITY;
        ALTER TABLE order_seats FORCE ROW LEVEL SECURITY;

        CREATE POLICY order_seats_tenant_isolation ON order_seats
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS order_seats_tenant_isolation ON order_seats;")
    op.execute("DROP TABLE IF EXISTS order_seats;")

    op.execute("""
        ALTER TABLE order_items
            DROP COLUMN IF EXISTS seat_no,
            DROP COLUMN IF EXISTS seat_label;
    """)

    op.execute("""
        ALTER TABLE orders
            DROP COLUMN IF EXISTS seat_count;
    """)
