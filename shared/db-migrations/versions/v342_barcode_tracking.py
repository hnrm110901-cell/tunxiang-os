"""v342 — 条码划菜追踪 (Barcode Dish Scan Tracking)

order_items 增加条码字段：barcode, barcode_scanned_at, scanned_by
新建 dish_scan_logs 表：扫码划菜日志（统计出品时效）

Revision: v342_barcode_tracking
"""

from alembic import op

revision = "v342_barcode_tracking"
down_revision = "v341_banquet_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. order_items 增加条码字段 ──
    op.execute("""
        ALTER TABLE order_items
            ADD COLUMN IF NOT EXISTS barcode          VARCHAR(30),
            ADD COLUMN IF NOT EXISTS barcode_scanned_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS scanned_by       UUID
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_items_barcode ON order_items (barcode) WHERE barcode IS NOT NULL")

    # ── 2. 新建 dish_scan_logs 表 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_scan_logs (
            id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            order_id            UUID            NOT NULL,
            order_item_id       UUID            NOT NULL,
            barcode             VARCHAR(30)     NOT NULL,
            dish_id             UUID,
            dish_name           VARCHAR(100),
            dept_id             UUID,
            ordered_at          TIMESTAMPTZ,
            scanned_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            duration_seconds    INT,
            scanned_by          UUID,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT dish_scan_logs_pkey PRIMARY KEY (id)
        )
    """)

    # ── 3. 索引 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_logs_store_date
            ON dish_scan_logs (tenant_id, store_id, scanned_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_logs_barcode
            ON dish_scan_logs (barcode)
    """)

    # ── 4. RLS策略 ──
    op.execute("ALTER TABLE dish_scan_logs ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS dish_scan_logs_tenant_isolation ON dish_scan_logs")
    op.execute("""
        CREATE POLICY dish_scan_logs_tenant_isolation ON dish_scan_logs
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE dish_scan_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dish_scan_logs CASCADE")
    op.execute("""
        ALTER TABLE order_items
            DROP COLUMN IF EXISTS barcode,
            DROP COLUMN IF EXISTS barcode_scanned_at,
            DROP COLUMN IF EXISTS scanned_by
    """)
