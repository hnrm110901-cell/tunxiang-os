"""v122 — 中央厨房：配方BOM + 生产计划 + 调拨单

新建：
  dish_recipes          — 标准配方（BOM），版本化管理
  recipe_ingredients    — 配方原料明细（含损耗率）
  ck_production_plans   — 中央厨房生产计划
  ck_plan_items         — 生产计划明细
  ck_dispatch_orders    — 配送调拨单（CK-YYYYMMDD-XXXX）
  ck_dispatch_items     — 调拨单明细

所有表含 tenant_id + RLS（app.tenant_id）。

Revision ID: v122
Revises: v121
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision = "v122"
down_revision = "v121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── dish_recipes 标准配方（BOM）────────────────────────────────────────────
    if "dish_recipes" not in _existing:
        op.create_table(
            "dish_recipes",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False,
                      comment="关联菜品ID（逻辑外键→dishes.id）"),
            sa.Column("version", sa.Integer, nullable=False, server_default="1",
                      comment="配方版本号，同菜品多版本共存"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true",
                      comment="是否激活版本"),
            sa.Column(
                "yield_qty", NUMERIC(10, 3), nullable=False, server_default="1.000",
                comment="产出量（份/kg 等）",
            ),
            sa.Column("yield_unit", sa.String(20), nullable=False, server_default="'portion'",
                      comment="产出单位（portion/kg/g/份）"),
            sa.Column("notes", sa.Text, nullable=True,
                      comment="配方说明"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_recipes' AND column_name IN ('tenant_id', 'dish_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_recipes_tenant_dish ON dish_recipes (tenant_id, dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_recipes' AND (column_name = 'dish_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_recipes_dish_id ON dish_recipes (dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_recipes' AND column_name IN ('tenant_id', 'dish_id', 'version')) = 3 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_recipes_dish_version ON dish_recipes (tenant_id, dish_id, version)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dish_recipes ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS dish_recipes_tenant ON dish_recipes;")
    op.execute("""
        CREATE POLICY dish_recipes_tenant ON dish_recipes
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # 确保 updated_at 触发器函数存在（v119 已创建，此处用 OR REPLACE 保证幂等）
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
        CREATE TRIGGER trg_dish_recipes_updated_at
        BEFORE UPDATE ON dish_recipes
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── recipe_ingredients 配方原料明细 ────────────────────────────────────────
    if "recipe_ingredients" not in _existing:
        op.create_table(
            "recipe_ingredients",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("recipe_id", UUID(as_uuid=True), nullable=False,
                      comment="关联dish_recipes.id"),
            sa.Column("ingredient_name", sa.String(100), nullable=False,
                      comment="原料名称"),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=True,
                      comment="可选关联原料库存表ID"),
            sa.Column(
                "qty", NUMERIC(10, 3), nullable=False,
                comment="标准用量（不含损耗）",
            ),
            sa.Column("unit", sa.String(20), nullable=False,
                      comment="单位：kg/g/ml/个/片"),
            sa.Column(
                "loss_rate", NUMERIC(5, 4), nullable=False, server_default="0.0000",
                comment="损耗率（0.05=5%）",
            ),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='recipe_ingredients' AND (column_name = 'recipe_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_recipe_ingredients_recipe_id ON recipe_ingredients (recipe_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='recipe_ingredients' AND column_name IN ('tenant_id', 'recipe_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_recipe_ingredients_tenant_recipe ON recipe_ingredients (tenant_id, recipe_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE recipe_ingredients ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS recipe_ingredients_tenant ON recipe_ingredients;")
    op.execute("""
        CREATE POLICY recipe_ingredients_tenant ON recipe_ingredients
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── ck_production_plans 中央厨房生产计划 ──────────────────────────────────
    if "ck_production_plans" not in _existing:
        op.create_table(
            "ck_production_plans",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("plan_date", sa.Date, nullable=False,
                      comment="计划生产日期"),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="'draft'",
                comment="计划状态: draft/confirmed/in_progress/done",
            ),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                      comment="为哪个门店生产（NULL=多门店）"),
            sa.Column("created_by", sa.String(100), nullable=True,
                      comment="创建人"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_plans' AND column_name IN ('tenant_id', 'plan_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_plans_tenant_date ON ck_production_plans (tenant_id, plan_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_production_plans' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_production_plans_status ON ck_production_plans (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_production_plans ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_production_plans_tenant ON ck_production_plans;")
    op.execute("""
        CREATE POLICY ck_production_plans_tenant ON ck_production_plans
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_production_plans_updated_at
        BEFORE UPDATE ON ck_production_plans
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_plan_items 生产计划明细 ─────────────────────────────────────────────
    if "ck_plan_items" not in _existing:
        op.create_table(
            "ck_plan_items",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("plan_id", UUID(as_uuid=True), nullable=False,
                      comment="关联ck_production_plans.id"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False,
                      comment="菜品ID"),
            sa.Column("recipe_id", UUID(as_uuid=True), nullable=True,
                      comment="关联dish_recipes.id（指定配方版本）"),
            sa.Column(
                "planned_qty", NUMERIC(10, 3), nullable=False,
                comment="计划产量",
            ),
            sa.Column(
                "actual_qty", NUMERIC(10, 3), nullable=True,
                comment="实际产量（完工后填入）",
            ),
            sa.Column("unit", sa.String(20), nullable=False, server_default="'portion'",
                      comment="数量单位"),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="'pending'",
                comment="明细状态: pending/in_progress/done/cancelled",
            ),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_plan_items' AND (column_name = 'plan_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_plan_items_plan_id ON ck_plan_items (plan_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_plan_items' AND (column_name = 'dish_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_plan_items_dish_id ON ck_plan_items (dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_plan_items' AND column_name IN ('tenant_id', 'plan_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_plan_items_tenant_plan ON ck_plan_items (tenant_id, plan_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_plan_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_plan_items_tenant ON ck_plan_items;")
    op.execute("""
        CREATE POLICY ck_plan_items_tenant ON ck_plan_items
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── ck_dispatch_orders 配送调拨单 ─────────────────────────────────────────
    if "ck_dispatch_orders" not in _existing:
        op.create_table(
            "ck_dispatch_orders",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dispatch_no", sa.String(50), nullable=False,
                      comment="调拨单号（自动生成 CK-YYYYMMDD-XXXX）"),
            sa.Column("plan_id", UUID(as_uuid=True), nullable=True,
                      comment="关联ck_production_plans.id"),
            sa.Column("from_store_id", UUID(as_uuid=True), nullable=True,
                      comment="来源（中央厨房，NULL=总厂）"),
            sa.Column("to_store_id", UUID(as_uuid=True), nullable=False,
                      comment="目标门店"),
            sa.Column("dispatch_date", sa.Date, nullable=False,
                      comment="计划配送日期"),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="'pending'",
                comment="调拨状态: pending/dispatched/received/rejected",
            ),
            sa.Column("driver_name", sa.String(50), nullable=True,
                      comment="司机姓名"),
            sa.Column("vehicle_no", sa.String(20), nullable=True,
                      comment="车牌号"),
            sa.Column("receiver_name", sa.String(50), nullable=True,
                      comment="收货人姓名"),
            sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=True,
                      comment="实际收货时间"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_orders' AND column_name IN ('tenant_id', 'dispatch_no')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_ck_dispatch_orders_no ON ck_dispatch_orders (tenant_id, dispatch_no)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_orders' AND column_name IN ('to_store_id', 'dispatch_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_dispatch_orders_to_store_date ON ck_dispatch_orders (to_store_id, dispatch_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_orders' AND column_name IN ('tenant_id', 'dispatch_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_dispatch_orders_tenant_date ON ck_dispatch_orders (tenant_id, dispatch_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_orders' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_dispatch_orders_status ON ck_dispatch_orders (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_dispatch_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_dispatch_orders_tenant ON ck_dispatch_orders;")
    op.execute("""
        CREATE POLICY ck_dispatch_orders_tenant ON ck_dispatch_orders
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("""
        CREATE TRIGGER trg_ck_dispatch_orders_updated_at
        BEFORE UPDATE ON ck_dispatch_orders
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── ck_dispatch_items 调拨单明细 ──────────────────────────────────────────
    if "ck_dispatch_items" not in _existing:
        op.create_table(
            "ck_dispatch_items",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dispatch_order_id", UUID(as_uuid=True), nullable=False,
                      comment="关联ck_dispatch_orders.id"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False,
                      comment="菜品ID"),
            sa.Column(
                "planned_qty", NUMERIC(10, 3), nullable=False,
                comment="计划调拨数量",
            ),
            sa.Column(
                "actual_qty", NUMERIC(10, 3), nullable=True,
                comment="实收量（门店确认收货时填入）",
            ),
            sa.Column("unit", sa.String(20), nullable=False,
                      comment="数量单位"),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_items' AND (column_name = 'dispatch_order_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_dispatch_items_order_id ON ck_dispatch_items (dispatch_order_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ck_dispatch_items' AND column_name IN ('tenant_id', 'dispatch_order_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ck_dispatch_items_tenant_order ON ck_dispatch_items (tenant_id, dispatch_order_id)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE ck_dispatch_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ck_dispatch_items_tenant ON ck_dispatch_items;")
    op.execute("""
        CREATE POLICY ck_dispatch_items_tenant ON ck_dispatch_items
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("ck_dispatch_items")
    op.drop_table("ck_dispatch_orders")
    op.drop_table("ck_plan_items")
    op.drop_table("ck_production_plans")
    op.drop_table("recipe_ingredients")
    op.drop_table("dish_recipes")
