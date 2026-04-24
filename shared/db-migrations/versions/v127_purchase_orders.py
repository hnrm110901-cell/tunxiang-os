"""v127 — 采购单管理表

新增三张表：
  purchase_orders      — 采购单主表（draft/pending_approval/approved/received/cancelled）
  purchase_order_items — 采购单明细行
  ingredient_batches   — 食材入库批次（效期/批次号追踪）

Revision ID: v127
Revises: v126
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v127"
down_revision = "v126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── purchase_orders 采购单主表 ─────────────────────────────────────────────
    if "purchase_orders" not in _existing:
        op.create_table(
            "purchase_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", UUID(as_uuid=True), nullable=True),
            sa.Column("po_number", sa.String(50), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="'draft'"),
            sa.Column("total_amount_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("expected_delivery_date", sa.Date, nullable=True),
            sa.Column("actual_delivery_date", sa.Date, nullable=True),
            sa.Column("approved_by", sa.String(100), nullable=True),
            sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='purchase_orders' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_purchase_orders_tenant_store ON purchase_orders (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='purchase_orders' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_purchase_orders_status ON purchase_orders (tenant_id, status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS purchase_orders_tenant_isolation ON purchase_orders;")
    op.execute("DROP POLICY IF EXISTS purchase_orders_tenant_isolation ON purchase_orders;")
    op.execute("""
        CREATE POLICY purchase_orders_tenant_isolation ON purchase_orders
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── purchase_order_items 采购单明细行 ──────────────────────────────────────
    if "purchase_order_items" not in _existing:
        op.create_table(
            "purchase_order_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("po_id", UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=True),
            sa.Column("ingredient_name", sa.String(100), nullable=False),
            sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("unit_price_fen", sa.Integer, nullable=False),
            sa.Column("subtotal_fen", sa.Integer, nullable=False),
            sa.Column("received_quantity", sa.Numeric(10, 3), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
        )

    op.execute("""
        DO $$ BEGIN
            ALTER TABLE purchase_order_items ADD CONSTRAINT fk_purchase_order_items_po
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='purchase_order_items' AND (column_name = 'po_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_purchase_order_items_po ON purchase_order_items (po_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS purchase_order_items_tenant_isolation ON purchase_order_items;")
    op.execute("DROP POLICY IF EXISTS purchase_order_items_tenant_isolation ON purchase_order_items;")
    op.execute("""
        CREATE POLICY purchase_order_items_tenant_isolation ON purchase_order_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── ingredient_batches 食材入库批次 ────────────────────────────────────────
    if "ingredient_batches" not in _existing:
        op.create_table(
            "ingredient_batches",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=False),
            sa.Column("po_id", UUID(as_uuid=True), nullable=True),
            sa.Column("batch_no", sa.String(50), nullable=True),
            sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("cost_per_unit_fen", sa.Integer, nullable=False),
            sa.Column("expiry_date", sa.Date, nullable=True),
            sa.Column("received_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("notes", sa.Text, nullable=True),
        )

    op.execute("""
        DO $$ BEGIN
            ALTER TABLE ingredient_batches ADD CONSTRAINT fk_ingredient_batches_po
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ingredient_batches' AND (column_name = 'ingredient_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ingredient_batches_ingredient ON ingredient_batches (ingredient_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ingredient_batches' AND column_name IN ('tenant_id', 'expiry_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ingredient_batches_expiry ON ingredient_batches (tenant_id, expiry_date)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ingredient_batches ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ingredient_batches_tenant_isolation ON ingredient_batches;")
    op.execute("DROP POLICY IF EXISTS ingredient_batches_tenant_isolation ON ingredient_batches;")
    op.execute("""
        CREATE POLICY ingredient_batches_tenant_isolation ON ingredient_batches
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    # 逆序删除：ingredient_batches → purchase_order_items → purchase_orders
    op.execute("DROP POLICY IF EXISTS ingredient_batches_tenant_isolation ON ingredient_batches;")
    op.drop_table("ingredient_batches")

    op.execute("DROP POLICY IF EXISTS purchase_order_items_tenant_isolation ON purchase_order_items;")
    op.drop_table("purchase_order_items")

    op.execute("DROP POLICY IF EXISTS purchase_orders_tenant_isolation ON purchase_orders;")
    op.drop_table("purchase_orders")
