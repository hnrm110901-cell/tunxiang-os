"""RLS foundation + 6 core entities

Revision ID: v001
Revises: None
Create Date: 2026-03-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSON

revision: str = "v001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# RLS 辅助函数
RLS_TABLES = [
    "customers", "stores", "dish_categories", "dishes", "dish_ingredients",
    "orders", "order_items", "ingredient_masters", "ingredients",
    "ingredient_transactions", "employees",
]


def _enable_rls(table_name: str) -> None:
    """为表启用 RLS + 创建租户隔离策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # RLS 基础函数
    op.execute("""
        CREATE OR REPLACE FUNCTION set_tenant_id(tid UUID) RETURNS VOID AS $$
        BEGIN
          PERFORM set_config('app.tenant_id', tid::TEXT, FALSE);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # --- stores ---
    op.create_table(
        "stores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_name", sa.String(100), nullable=False),
        sa.Column("store_code", sa.String(20), unique=True, nullable=False),
        sa.Column("address", sa.String(255)),
        sa.Column("city", sa.String(50)),
        sa.Column("district", sa.String(50)),
        sa.Column("phone", sa.String(20)),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("brand_id", sa.String(50), index=True),
        sa.Column("region", sa.String(50)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("area", sa.Float),
        sa.Column("seats", sa.Integer),
        sa.Column("floors", sa.Integer, server_default="1"),
        sa.Column("opening_date", sa.String(20)),
        sa.Column("business_hours", JSON),
        sa.Column("config", JSON),
        sa.Column("monthly_revenue_target_fen", sa.Integer),
        sa.Column("daily_customer_target", sa.Integer),
        sa.Column("cost_ratio_target", sa.Float),
        sa.Column("labor_cost_ratio_target", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("primary_phone", sa.String(20), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100)),
        sa.Column("gender", sa.String(10)),
        sa.Column("birth_date", sa.Date),
        sa.Column("anniversary", sa.Date),
        sa.Column("wechat_openid", sa.String(128), index=True),
        sa.Column("wechat_unionid", sa.String(128), index=True),
        sa.Column("wechat_nickname", sa.String(100)),
        sa.Column("wechat_avatar_url", sa.String(500)),
        sa.Column("total_order_count", sa.Integer, server_default="0"),
        sa.Column("total_order_amount_fen", sa.Integer, server_default="0"),
        sa.Column("total_reservation_count", sa.Integer, server_default="0"),
        sa.Column("first_order_at", sa.DateTime(timezone=True)),
        sa.Column("last_order_at", sa.DateTime(timezone=True), index=True),
        sa.Column("first_store_id", sa.String(50)),
        sa.Column("rfm_recency_days", sa.Integer),
        sa.Column("rfm_frequency", sa.Integer),
        sa.Column("rfm_monetary_fen", sa.Integer),
        sa.Column("rfm_level", sa.String(5), server_default="S3"),
        sa.Column("tags", JSON),
        sa.Column("dietary_restrictions", JSON),
        sa.Column("is_merged", sa.Boolean, server_default="false", index=True),
        sa.Column("merged_into", UUID(as_uuid=True), index=True),
        sa.Column("source", sa.String(50)),
        sa.Column("confidence_score", sa.Float, server_default="1.0"),
        sa.Column("extra", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_customer_phone_active", "customers", ["primary_phone", "is_merged"])

    # --- employees ---
    op.create_table(
        "employees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("emp_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("email", sa.String(100)),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("skills", ARRAY(sa.String)),
        sa.Column("hire_date", sa.Date),
        sa.Column("employment_status", sa.String(20), server_default="regular"),
        sa.Column("employment_type", sa.String(30), server_default="regular"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("probation_end_date", sa.Date),
        sa.Column("grade_level", sa.String(50)),
        sa.Column("wechat_userid", sa.String(100), index=True),
        sa.Column("dingtalk_userid", sa.String(100), index=True),
        sa.Column("gender", sa.String(10)),
        sa.Column("birth_date", sa.Date),
        sa.Column("education", sa.String(20)),
        sa.Column("health_cert_expiry", sa.Date),
        sa.Column("id_card_no", sa.String(200)),
        sa.Column("daily_wage_standard_fen", sa.Integer),
        sa.Column("work_hour_type", sa.String(30)),
        sa.Column("bank_name", sa.String(100)),
        sa.Column("bank_account", sa.String(200)),
        sa.Column("emergency_contact", sa.String(50)),
        sa.Column("emergency_phone", sa.String(20)),
        sa.Column("org_id", UUID(as_uuid=True), index=True),
        sa.Column("preferences", JSON),
        sa.Column("performance_score", sa.String(10)),
        sa.Column("training_completed", ARRAY(sa.String)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- dish_categories + dishes + dish_ingredients ---
    op.create_table(
        "dish_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50)),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("dish_categories.id")),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    op.create_table(
        "dishes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_name", sa.String(100), nullable=False),
        sa.Column("dish_code", sa.String(50), unique=True, nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("dish_categories.id")),
        sa.Column("description", sa.Text),
        sa.Column("image_url", sa.String(500)),
        sa.Column("price_fen", sa.Integer, nullable=False),
        sa.Column("original_price_fen", sa.Integer),
        sa.Column("cost_fen", sa.Integer),
        sa.Column("profit_margin", sa.Numeric(5, 2)),
        sa.Column("unit", sa.String(20), server_default="份"),
        sa.Column("serving_size", sa.String(50)),
        sa.Column("spicy_level", sa.Integer, server_default="0"),
        sa.Column("preparation_time", sa.Integer),
        sa.Column("cooking_method", sa.String(50)),
        sa.Column("kitchen_station", sa.String(50)),
        sa.Column("tags", ARRAY(sa.String)),
        sa.Column("allergens", ARRAY(sa.String)),
        sa.Column("dietary_info", ARRAY(sa.String)),
        sa.Column("calories", sa.Integer),
        sa.Column("protein", sa.Numeric(5, 2)),
        sa.Column("fat", sa.Numeric(5, 2)),
        sa.Column("carbohydrate", sa.Numeric(5, 2)),
        sa.Column("is_available", sa.Boolean, server_default="true"),
        sa.Column("is_recommended", sa.Boolean, server_default="false"),
        sa.Column("is_seasonal", sa.Boolean, server_default="false"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("total_sales", sa.Integer, server_default="0"),
        sa.Column("total_revenue_fen", sa.Integer, server_default="0"),
        sa.Column("rating", sa.Numeric(3, 2)),
        sa.Column("review_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    op.create_table(
        "dish_ingredients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("ingredient_id", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("cost_per_serving_fen", sa.Integer),
        sa.Column("is_required", sa.Boolean, server_default="true"),
        sa.Column("is_substitutable", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- orders + order_items ---
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_no", sa.String(64), unique=True, nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("table_number", sa.String(20)),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), index=True),
        sa.Column("waiter_id", sa.String(50), index=True),
        sa.Column("sales_channel", sa.String(30), index=True),
        sa.Column("total_amount_fen", sa.Integer, nullable=False),
        sa.Column("discount_amount_fen", sa.Integer, server_default="0"),
        sa.Column("final_amount_fen", sa.Integer),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("order_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.String(500)),
        sa.Column("order_metadata", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("idx_order_store_status", "orders", ["store_id", "status"])
    op.create_index("idx_order_store_time", "orders", ["store_id", "order_time"])

    op.create_table(
        "order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id")),
        sa.Column("item_name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_fen", sa.Integer, nullable=False),
        sa.Column("subtotal_fen", sa.Integer, nullable=False),
        sa.Column("food_cost_fen", sa.Integer),
        sa.Column("gross_margin", sa.Numeric(6, 4)),
        sa.Column("notes", sa.String(255)),
        sa.Column("customizations", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # --- ingredient_masters + ingredients + ingredient_transactions ---
    op.create_table(
        "ingredient_masters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("canonical_name", sa.String(100), nullable=False),
        sa.Column("aliases", ARRAY(sa.String(100))),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("sub_category", sa.String(30)),
        sa.Column("base_unit", sa.String(10), nullable=False),
        sa.Column("spec_desc", sa.String(100)),
        sa.Column("shelf_life_days", sa.Integer),
        sa.Column("storage_type", sa.String(20), nullable=False, server_default="ambient"),
        sa.Column("storage_temp_min", sa.Numeric(5, 1)),
        sa.Column("storage_temp_max", sa.Numeric(5, 1)),
        sa.Column("is_traceable", sa.Boolean, server_default="false"),
        sa.Column("allergen_tags", ARRAY(sa.String(30))),
        sa.Column("seasonality", ARRAY(sa.String(2))),
        sa.Column("typical_waste_pct", sa.Numeric(5, 2)),
        sa.Column("typical_yield_rate", sa.Numeric(5, 4)),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    op.create_table(
        "ingredients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("ingredient_name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("current_quantity", sa.Float, server_default="0"),
        sa.Column("min_quantity", sa.Float, nullable=False),
        sa.Column("max_quantity", sa.Float),
        sa.Column("unit_price_fen", sa.Integer),
        sa.Column("status", sa.String(20), server_default="normal", index=True),
        sa.Column("supplier_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    op.create_table(
        "ingredient_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredients.id"), nullable=False, index=True),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("unit_cost_fen", sa.Integer),
        sa.Column("reference_id", sa.String(100)),
        sa.Column("notes", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )

    # Enable RLS on all tables
    for table in RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        _disable_rls(table)

    op.drop_table("ingredient_transactions")
    op.drop_table("ingredients")
    op.drop_table("ingredient_masters")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("dish_ingredients")
    op.drop_table("dishes")
    op.drop_table("dish_categories")
    op.drop_table("employees")
    op.drop_table("customers")
    op.drop_table("stores")

    op.execute("DROP FUNCTION IF EXISTS set_tenant_id(UUID)")
