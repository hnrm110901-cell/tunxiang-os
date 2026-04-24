"""v119 — 中央厨房核心模块

新建：
  dish_boms             — 菜品BOM配方表（版本化）
  dish_bom_items        — BOM明细行（食材清单+损耗率）
  ck_production_orders  — 中央厨房生产工单
  ck_production_items   — 生产工单明细
  ck_distribution_orders — 中央厨房→门店配送单
  ck_distribution_items  — 配送单明细

所有表含 tenant_id + RLS（app.tenant_id）+ updated_at 自动触发器。

Revision ID: v119
Revises: v118
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import NUMERIC, UUID

revision = "v119"
down_revision = "v118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── dish_boms 菜品BOM配方表 ────────────────────────────────────────────────
    if "dish_boms" not in _existing:
        op.create_table(
            "dish_boms",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False, comment="关联菜品ID（FK→dishes.id，逻辑外键）"),
            sa.Column("version", sa.Integer, nullable=False, server_default="1", comment="BOM版本号，同菜品多版本共存"),
            sa.Column(
                "total_cost_fen",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="BOM汇总成本（分），由calculate-cost接口计算后写入",
            ),
            sa.Column(
                "yield_qty",
                NUMERIC(10, 3),
                nullable=False,
                server_default="1.000",
                comment="标准产出数量（如1份、500g等）",
            ),
            sa.Column(
                "yield_unit", sa.String(20), nullable=False, server_default="'份'", comment="产出单位（份/kg/g/L等）"
            ),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default="false",
                comment="是否激活版本（同菜品只能有一个激活版本）",
            ),
            sa.Column("notes", sa.String(500), nullable=True, comment="备注说明"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_boms' AND column_name IN ('tenant_id', 'dish_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_boms_tenant_dish ON dish_boms (tenant_id, dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_boms' AND (column_name = 'dish_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_boms_dish_id ON dish_boms (dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_boms' AND (column_name = 'is_active')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_boms_is_active ON dish_boms (is_active)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_boms' AND column_name IN ('tenant_id', 'dish_id', 'version')) = 3 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_boms_dish_version ON dish_boms (tenant_id, dish_id, version)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dish_boms ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS dish_boms_tenant_isolation ON dish_boms;")
    op.execute("""
        CREATE POLICY dish_boms_tenant_isolation ON dish_boms
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION trg_set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_dish_boms_updated_at
        BEFORE UPDATE ON dish_boms
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── dish_bom_items BOM明细行 ───────────────────────────────────────────────
    if "dish_bom_items" not in _existing:
        op.create_table(
            "dish_bom_items",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("bom_id", UUID(as_uuid=True), nullable=False, comment="关联dish_boms.id"),
            sa.Column("ingredient_name", sa.String(100), nullable=False, comment="食材名称（冗余存储，便于查询）"),
            sa.Column("ingredient_code", sa.String(50), nullable=True, comment="食材编码（对应食材主档编码）"),
            sa.Column(
                "quantity",
                NUMERIC(10, 3),
                nullable=False,
                comment="标准用量（不含损耗）",
            ),
            sa.Column("unit", sa.String(20), nullable=False, comment="单位：kg/g/L/mL/个/份"),
            sa.Column(
                "unit_cost_fen",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="单位成本（分/单位），用于计算该行成本",
            ),
            sa.Column(
                "total_cost_fen",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="该行合计成本（分）= quantity × unit_cost × (1 + loss_rate)",
            ),
            sa.Column(
                "loss_rate",
                NUMERIC(5, 4),
                nullable=False,
                server_default="0.0500",
                comment="损耗率，默认5%（0.0500），如10%填0.1000",
            ),
            sa.Column(
                "is_semi_product",
                sa.Boolean,
                nullable=False,
                server_default="false",
                comment="是否为半成品（true时可关联另一张BOM递归展开）",
            ),
            sa.Column(
                "semi_product_bom_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="半成品BOM ID（is_semi_product=true时关联dish_boms.id）",
            ),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0", comment="排序序号"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_bom_items' AND (column_name = 'bom_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_bom_items_bom_id ON dish_bom_items (bom_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_bom_items' AND column_name IN ('tenant_id', 'bom_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_bom_items_tenant_bom ON dish_bom_items (tenant_id, bom_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_bom_items' AND (column_name = 'ingredient_code')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_bom_items_ingredient_code ON dish_bom_items (ingredient_code)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE dish_bom_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS dish_bom_items_tenant_isolation ON dish_bom_items;")
    op.execute("""
        CREATE POLICY dish_bom_items_tenant_isolation ON dish_bom_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)
    op.execute("""
        CREATE TRIGGER trg_dish_bom_items_updated_at
        BEFORE UPDATE ON dish_bom_items
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_production_orders 生产工单 ─────────────────────────────────────────
    if "ck_production_orders" not in _existing:
        op.create_table(
            "ck_production_orders",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False, comment="工单编号（如CK-20260402-0001），全局唯一"),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="中央厨房门店ID（作为kitchen标识）"),
            sa.Column("production_date", sa.Date, nullable=False, comment="计划生产日期"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'draft'",
                comment="工单状态: draft/confirmed/producing/completed/cancelled",
            ),
            sa.Column("total_items", sa.Integer, nullable=False, server_default="0", comment="工单总菜品种数"),
            sa.Column(
                "completed_items", sa.Integer, nullable=False, server_default="0", comment="已完成生产的菜品种数"
            ),
            sa.Column("notes", sa.String(500), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_orders' AND column_name IN ('tenant_id', 'order_no')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_ck_production_orders_no ON ck_production_orders (tenant_id, order_no)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_orders' AND column_name IN ('store_id', 'production_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_orders_store_date ON ck_production_orders (store_id, production_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_orders' AND column_name IN ('tenant_id', 'production_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_orders_tenant_date ON ck_production_orders (tenant_id, production_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_orders' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_orders_status ON ck_production_orders (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_production_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_production_orders_tenant_isolation ON ck_production_orders;")
    op.execute("""
        CREATE POLICY ck_production_orders_tenant_isolation ON ck_production_orders
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_production_orders_updated_at
        BEFORE UPDATE ON ck_production_orders
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_production_items 生产工单明细 ──────────────────────────────────────
    if "ck_production_items" not in _existing:
        op.create_table(
            "ck_production_items",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=False, comment="关联ck_production_orders.id"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False, comment="菜品ID"),
            sa.Column("dish_name", sa.String(100), nullable=False, comment="菜品名称（冗余）"),
            sa.Column(
                "quantity",
                NUMERIC(10, 3),
                nullable=False,
                comment="计划生产数量",
            ),
            sa.Column("unit", sa.String(20), nullable=False, server_default="'份'", comment="数量单位"),
            sa.Column("bom_id", UUID(as_uuid=True), nullable=True, comment="关联dish_boms.id，记录生产时使用的BOM版本"),
            sa.Column(
                "estimated_cost_fen",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="预估成本（分）= quantity × bom.total_cost_fen",
            ),
            sa.Column("actual_cost_fen", sa.Integer, nullable=True, comment="实际成本（分），完工后填入"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="明细状态: pending/producing/completed",
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_items' AND (column_name = 'order_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_items_order_id ON ck_production_items (order_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_items' AND (column_name = 'dish_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_items_dish_id ON ck_production_items (dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_items' AND column_name IN ('tenant_id', 'order_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_items_tenant_order ON ck_production_items (tenant_id, order_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_production_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_production_items_tenant_isolation ON ck_production_items;")
    op.execute("""
        CREATE POLICY ck_production_items_tenant_isolation ON ck_production_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_production_items_updated_at
        BEFORE UPDATE ON ck_production_items
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_distribution_orders 配送单 ─────────────────────────────────────────
    if "ck_distribution_orders" not in _existing:
        op.create_table(
            "ck_distribution_orders",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_no", sa.String(64), nullable=False, comment="配送单编号（如CKD-20260402-0001），全局唯一"),
            sa.Column(
                "from_kitchen_id", UUID(as_uuid=True), nullable=False, comment="发货方中央厨房ID（store_id格式）"
            ),
            sa.Column("to_store_id", UUID(as_uuid=True), nullable=False, comment="收货方门店ID"),
            sa.Column("distribution_date", sa.Date, nullable=False, comment="计划配送日期"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="配送状态: pending/shipped/received/confirmed",
            ),
            sa.Column("total_items", sa.Integer, nullable=False, server_default="0", comment="配送菜品种数"),
            sa.Column("carrier_name", sa.String(50), nullable=True, comment="承运人/司机姓名"),
            sa.Column("tracking_no", sa.String(100), nullable=True, comment="物流单号/追踪编号"),
            sa.Column("notes", sa.String(500), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_orders' AND column_name IN ('tenant_id', 'order_no')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_ck_distribution_orders_no ON ck_distribution_orders (tenant_id, order_no)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_orders' AND column_name IN ('to_store_id', 'distribution_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_orders_to_store_date ON ck_distribution_orders (to_store_id, distribution_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_orders' AND (column_name = 'from_kitchen_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_orders_from_kitchen ON ck_distribution_orders (from_kitchen_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_orders' AND column_name IN ('tenant_id', 'distribution_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_orders_tenant_date ON ck_distribution_orders (tenant_id, distribution_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_orders' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_orders_status ON ck_distribution_orders (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_distribution_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_distribution_orders_tenant_isolation ON ck_distribution_orders;")
    op.execute("""
        CREATE POLICY ck_distribution_orders_tenant_isolation ON ck_distribution_orders
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_distribution_orders_updated_at
        BEFORE UPDATE ON ck_distribution_orders
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_distribution_items 配送单明细 ──────────────────────────────────────
    if "ck_distribution_items" not in _existing:
        op.create_table(
            "ck_distribution_items",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("distribution_id", UUID(as_uuid=True), nullable=False, comment="关联ck_distribution_orders.id"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False, comment="菜品ID"),
            sa.Column("dish_name", sa.String(100), nullable=False, comment="菜品名称（冗余）"),
            sa.Column(
                "quantity",
                NUMERIC(10, 3),
                nullable=False,
                comment="配送数量",
            ),
            sa.Column("unit", sa.String(20), nullable=False, server_default="'份'", comment="数量单位"),
            sa.Column("bom_id", UUID(as_uuid=True), nullable=True, comment="关联dish_boms.id，记录该批次使用的BOM版本"),
            sa.Column("estimated_cost_fen", sa.Integer, nullable=False, server_default="0", comment="预估成本（分）"),
            sa.Column(
                "actual_received_qty",
                NUMERIC(10, 3),
                nullable=True,
                comment="门店实收数量（门店确认收货时填入）",
            ),
            sa.Column("notes", sa.String(300), nullable=True, comment="明细备注/差异说明"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_items' AND (column_name = 'distribution_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_items_distribution_id ON ck_distribution_items (distribution_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_items' AND (column_name = 'dish_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_items_dish_id ON ck_distribution_items (dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_distribution_items' AND column_name IN ('tenant_id', 'distribution_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_distribution_items_tenant_dist ON ck_distribution_items (tenant_id, distribution_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_distribution_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_distribution_items_tenant_isolation ON ck_distribution_items;")
    op.execute("""
        CREATE POLICY ck_distribution_items_tenant_isolation ON ck_distribution_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_distribution_items_updated_at
        BEFORE UPDATE ON ck_distribution_items
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)


def downgrade() -> None:
    op.drop_table("ck_distribution_items")
    op.drop_table("ck_distribution_orders")
    op.drop_table("ck_production_items")
    op.drop_table("ck_production_orders")
    op.drop_table("dish_bom_items")
    op.drop_table("dish_boms")
    op.execute("DROP FUNCTION IF EXISTS trg_set_updated_at() CASCADE;")
