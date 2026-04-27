"""v010: Sync ORM model columns to DB — add missing columns from entity evolution

Audit found that ORM models in shared/ontology/src/entities.py and
services/tx-trade/src/models/ have evolved beyond what migrations v001-v009
created. This migration adds all missing columns and indexes.

Tables affected:
  - stores: 20+ new fields (store_type, email, manager_id, etc.)
  - customers: 6 new fields (r_score, f_score, m_score, etc.)
  - dish_categories: 2 new fields (store_id, description)
  - dishes: 11+ new fields (store_id, production_dept_id, season, etc.)
  - orders: 12+ new fields (order_type, guest_count, abnormal_flag, etc.)
  - order_items: 7 new fields (pricing_mode, weight_value, gift_flag, etc.)
  - dish_ingredients: 2 new fields (substitute_ids, notes)
  - ingredients: 1 new field (supplier_contact)
  - ingredient_transactions: 5 new fields (store_id, total_cost_fen, etc.)
  - employees: 8 new fields (health_cert_attachment, bank_branch, etc.)
  - production_depts: 3 new fields (store_id, printer_address, default_timeout_minutes)
  - dish_dept_mappings: 1 new field (sort_order)

Also adds missing FK indexes:
  - dish_categories.parent_id
  - dishes.category_id
  - refunds.payment_id

Revision ID: v010
Revises: v009
Create Date: 2026-03-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID

revision = "v010"
down_revision = "v009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =====================================================================
    # stores — 20+ missing columns
    # =====================================================================
    op.add_column("stores", sa.Column("email", sa.String(100), comment="门店邮箱"))
    op.add_column("stores", sa.Column("manager_id", UUID(as_uuid=True), comment="店长ID"))
    op.add_column("stores", sa.Column("is_active", sa.Boolean, server_default="true", comment="是否营业中"))
    op.add_column(
        "stores",
        sa.Column(
            "store_type",
            sa.String(30),
            nullable=False,
            server_default="physical",
            comment="physical/virtual/central_kitchen/warehouse",
        ),
    )
    op.add_column(
        "stores",
        sa.Column(
            "has_physical_seats",
            sa.Boolean,
            server_default="true",
            comment="True for restaurants, False for warehouses/virtual",
        ),
    )
    op.add_column("stores", sa.Column("turnover_rate_target", sa.Float, comment="翻台率目标"))
    op.add_column(
        "stores", sa.Column("serve_time_limit_min", sa.Integer, server_default="30", comment="出餐时限(分钟)")
    )
    op.add_column("stores", sa.Column("waste_rate_target", sa.Float, comment="损耗率目标(%)"))
    op.add_column("stores", sa.Column("rectification_close_rate", sa.Float, comment="整改关闭率"))
    op.add_column("stores", sa.Column("meal_periods", JSON, comment="餐段配置[{name,start,end}]"))
    op.add_column(
        "stores",
        sa.Column("business_type", sa.String(30), comment="fine_dining/fast_food/retail/catering/pro/standard/lite"),
    )
    op.add_column("stores", sa.Column("store_category", sa.String(50), comment="门店类别：商场店/街边店/社区店"))
    op.add_column("stores", sa.Column("store_tags", JSON, comment="门店标签"))
    op.add_column("stores", sa.Column("operation_mode", sa.String(20), comment="经营模式：直营/加盟/联营"))
    op.add_column("stores", sa.Column("store_level", sa.String(20), comment="门店等级：A/B/C/D"))
    op.add_column("stores", sa.Column("last_online_at", sa.DateTime(timezone=True), comment="最近在线日期"))
    op.add_column("stores", sa.Column("license_expiry", sa.Date, comment="授权到期日期"))
    op.add_column(
        "stores", sa.Column("settlement_mode", sa.String(20), server_default="auto+manual", comment="日结方式")
    )
    op.add_column("stores", sa.Column("shift_type", sa.String(20), server_default="no_shift", comment="班别"))
    op.add_column("stores", sa.Column("metadata", JSON, comment="灵活扩展字段"))

    # =====================================================================
    # customers — 6 missing columns
    # =====================================================================
    op.add_column("customers", sa.Column("r_score", sa.Integer, comment="R评分1-5"))
    op.add_column("customers", sa.Column("f_score", sa.Integer, comment="F评分1-5"))
    op.add_column("customers", sa.Column("m_score", sa.Integer, comment="M评分1-5"))
    op.add_column("customers", sa.Column("rfm_updated_at", sa.DateTime(timezone=True), comment="RFM最近更新时间"))
    op.add_column(
        "customers", sa.Column("store_quadrant", sa.String(20), comment="benchmark/defensive/potential/breakthrough")
    )
    op.add_column("customers", sa.Column("risk_score", sa.Float, server_default="0", comment="流失风险分0-1"))

    # =====================================================================
    # dish_categories — 2 missing columns
    # =====================================================================
    op.add_column("dish_categories", sa.Column("store_id", UUID(as_uuid=True), comment="所属门店，NULL=集团通用分类"))
    op.add_column("dish_categories", sa.Column("description", sa.Text, comment="分类描述"))
    op.create_index("idx_dish_categories_store_id", "dish_categories", ["store_id"])
    op.create_foreign_key("fk_dish_categories_store_id", "dish_categories", "stores", ["store_id"], ["id"])

    # =====================================================================
    # dishes — 11+ missing columns
    # =====================================================================
    op.add_column("dishes", sa.Column("store_id", UUID(as_uuid=True), comment="所属门店，NULL=集团通用菜品"))
    op.add_column("dishes", sa.Column("production_dept_id", UUID(as_uuid=True), comment="出品部门ID"))
    op.add_column("dishes", sa.Column("sell_start_date", sa.Date, comment="售卖开始日期"))
    op.add_column("dishes", sa.Column("sell_end_date", sa.Date, comment="售卖结束日期"))
    op.add_column("dishes", sa.Column("sell_time_ranges", JSON, comment="售卖时段[{start,end}]"))
    op.add_column("dishes", sa.Column("season", sa.String(20), comment="季节：春/夏/秋/冬"))
    op.add_column(
        "dishes", sa.Column("requires_inventory", sa.Boolean, server_default="true", comment="是否需要库存管理")
    )
    op.add_column("dishes", sa.Column("low_stock_threshold", sa.Integer, comment="低库存预警阈值(份)"))
    op.add_column("dishes", sa.Column("dish_master_id", UUID(as_uuid=True), comment="集团菜品主档ID"))
    op.add_column("dishes", sa.Column("notes", sa.Text, comment="菜品备注"))
    op.add_column("dishes", sa.Column("dish_metadata", JSON, comment="扩展字段"))
    op.create_index("idx_dishes_store_id", "dishes", ["store_id"])
    op.create_index("idx_dishes_dish_master_id", "dishes", ["dish_master_id"])
    op.create_foreign_key("fk_dishes_store_id", "dishes", "stores", ["store_id"], ["id"])

    # =====================================================================
    # orders — 12+ missing columns
    # =====================================================================
    op.add_column("orders", sa.Column("customer_name", sa.String(100), comment="散客姓名(未关联CDP)"))
    op.add_column("orders", sa.Column("customer_phone", sa.String(20), comment="散客手机(未关联CDP)"))
    op.add_column(
        "orders",
        sa.Column(
            "order_type",
            sa.String(30),
            nullable=False,
            server_default="dine_in",
            comment="dine_in/takeaway/delivery/retail/catering/banquet",
        ),
    )
    op.add_column("orders", sa.Column("sales_channel_id", sa.String(50), comment="引用SalesChannel配置表"))
    op.add_column("orders", sa.Column("guest_count", sa.Integer, comment="就餐人数"))
    op.add_column("orders", sa.Column("dining_duration_min", sa.Integer, comment="就餐时长(分钟)"))
    op.add_column("orders", sa.Column("abnormal_flag", sa.Boolean, server_default="false", comment="异常标记"))
    op.add_column("orders", sa.Column("abnormal_type", sa.String(50), comment="complaint/return/discount/timeout"))
    op.add_column("orders", sa.Column("discount_type", sa.String(50), comment="折扣类型:coupon/vip/manager/promotion"))
    op.add_column("orders", sa.Column("margin_alert_flag", sa.Boolean, server_default="false", comment="毛利告警"))
    op.add_column("orders", sa.Column("gross_margin_before", sa.Numeric(6, 4), comment="折扣前毛利率"))
    op.add_column("orders", sa.Column("gross_margin_after", sa.Numeric(6, 4), comment="折扣后毛利率"))
    op.add_column("orders", sa.Column("served_at", sa.DateTime(timezone=True), comment="出餐完成时间"))
    op.add_column("orders", sa.Column("serve_duration_min", sa.Integer, comment="出餐耗时(分钟)"))
    op.create_index("idx_orders_sales_channel_id", "orders", ["sales_channel_id"])

    # =====================================================================
    # order_items — 7 missing columns
    # =====================================================================
    op.add_column("order_items", sa.Column("pricing_mode", sa.String(20), comment="fixed/weight/market_price"))
    op.add_column("order_items", sa.Column("weight_value", sa.Numeric(8, 3), comment="称重值(kg)"))
    op.add_column("order_items", sa.Column("gift_flag", sa.Boolean, server_default="false", comment="赠送标记"))
    op.add_column("order_items", sa.Column("sent_to_kds_flag", sa.Boolean, server_default="false", comment="已发送KDS"))
    op.add_column("order_items", sa.Column("kds_station", sa.String(50), comment="目标档口"))
    op.add_column("order_items", sa.Column("return_flag", sa.Boolean, server_default="false", comment="退菜标记"))
    op.add_column("order_items", sa.Column("return_reason", sa.String(200), comment="退菜原因"))

    # =====================================================================
    # dish_ingredients — 2 missing columns
    # =====================================================================
    op.add_column(
        "dish_ingredients", sa.Column("substitute_ids", ARRAY(UUID(as_uuid=True)), comment="可替代食材ID列表")
    )
    op.add_column("dish_ingredients", sa.Column("notes", sa.Text, comment="配方备注"))

    # =====================================================================
    # ingredients — 1 missing column
    # =====================================================================
    op.add_column("ingredients", sa.Column("supplier_contact", sa.String(100), comment="供应商联系方式"))

    # =====================================================================
    # ingredient_transactions — 5 missing columns
    # =====================================================================
    op.add_column("ingredient_transactions", sa.Column("store_id", UUID(as_uuid=True), comment="门店ID(便于按店查询)"))
    op.add_column("ingredient_transactions", sa.Column("total_cost_fen", sa.Integer, comment="总成本(分)"))
    op.add_column("ingredient_transactions", sa.Column("quantity_before", sa.Float, comment="操作前库存量"))
    op.add_column("ingredient_transactions", sa.Column("quantity_after", sa.Float, comment="操作后库存量"))
    op.add_column("ingredient_transactions", sa.Column("performed_by", sa.String(100), comment="操作人"))
    op.add_column(
        "ingredient_transactions",
        sa.Column("transaction_time", sa.DateTime(timezone=True), server_default=sa.func.now(), comment="操作时间"),
    )
    op.create_foreign_key(
        "fk_ingredient_transactions_store_id", "ingredient_transactions", "stores", ["store_id"], ["id"]
    )
    op.create_index("idx_ingredient_transactions_store_id", "ingredient_transactions", ["store_id"])

    # =====================================================================
    # employees — 8 missing columns
    # =====================================================================
    op.add_column("employees", sa.Column("health_cert_attachment", sa.String(500), comment="健康证附件路径"))
    op.add_column("employees", sa.Column("id_card_expiry", sa.Date, comment="身份证到期日"))
    op.add_column("employees", sa.Column("background_check", sa.String(50), comment="背调状态:pending/passed/failed"))
    op.add_column("employees", sa.Column("first_work_date", sa.Date, comment="首次工作日期"))
    op.add_column("employees", sa.Column("regular_date", sa.Date, comment="转正日期"))
    op.add_column("employees", sa.Column("seniority_months", sa.Integer, comment="司龄(月)"))
    op.add_column("employees", sa.Column("bank_branch", sa.String(200), comment="开户行支行"))
    op.add_column("employees", sa.Column("emergency_relation", sa.String(20), comment="与紧急联系人关系"))

    # =====================================================================
    # production_depts — 3 missing columns
    # =====================================================================
    op.add_column("production_depts", sa.Column("store_id", UUID(as_uuid=True), comment="门店ID（NULL表示品牌级通用）"))
    op.add_column("production_depts", sa.Column("printer_address", sa.String(100), comment="档口打印机地址 host:port"))
    op.add_column(
        "production_depts",
        sa.Column("default_timeout_minutes", sa.Integer, server_default="15", comment="默认出品时限(分钟)"),
    )
    op.create_index("idx_production_depts_store_id", "production_depts", ["store_id"])

    # =====================================================================
    # dish_dept_mappings — 1 missing column
    # =====================================================================
    op.add_column(
        "dish_dept_mappings", sa.Column("sort_order", sa.Integer, server_default="0", comment="菜品在该档口内的排序")
    )

    # =====================================================================
    # Missing FK indexes (foreign keys without indexes hurt query performance)
    # =====================================================================
    op.create_index("idx_dish_categories_parent_id", "dish_categories", ["parent_id"])
    op.create_index("idx_dishes_category_id", "dishes", ["category_id"])
    op.create_index("idx_refunds_payment_id", "refunds", ["payment_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_refunds_payment_id", table_name="refunds")
    op.drop_index("idx_dishes_category_id", table_name="dishes")
    op.drop_index("idx_dish_categories_parent_id", table_name="dish_categories")

    # dish_dept_mappings
    op.drop_column("dish_dept_mappings", "sort_order")

    # production_depts
    op.drop_index("idx_production_depts_store_id", table_name="production_depts")
    op.drop_column("production_depts", "default_timeout_minutes")
    op.drop_column("production_depts", "printer_address")
    op.drop_column("production_depts", "store_id")

    # employees
    op.drop_column("employees", "emergency_relation")
    op.drop_column("employees", "bank_branch")
    op.drop_column("employees", "seniority_months")
    op.drop_column("employees", "regular_date")
    op.drop_column("employees", "first_work_date")
    op.drop_column("employees", "background_check")
    op.drop_column("employees", "id_card_expiry")
    op.drop_column("employees", "health_cert_attachment")

    # ingredient_transactions
    op.drop_index("idx_ingredient_transactions_store_id", table_name="ingredient_transactions")
    op.drop_constraint("fk_ingredient_transactions_store_id", "ingredient_transactions", type_="foreignkey")
    op.drop_column("ingredient_transactions", "transaction_time")
    op.drop_column("ingredient_transactions", "performed_by")
    op.drop_column("ingredient_transactions", "quantity_after")
    op.drop_column("ingredient_transactions", "quantity_before")
    op.drop_column("ingredient_transactions", "total_cost_fen")
    op.drop_column("ingredient_transactions", "store_id")

    # ingredients
    op.drop_column("ingredients", "supplier_contact")

    # dish_ingredients
    op.drop_column("dish_ingredients", "notes")
    op.drop_column("dish_ingredients", "substitute_ids")

    # order_items
    op.drop_column("order_items", "return_reason")
    op.drop_column("order_items", "return_flag")
    op.drop_column("order_items", "kds_station")
    op.drop_column("order_items", "sent_to_kds_flag")
    op.drop_column("order_items", "gift_flag")
    op.drop_column("order_items", "weight_value")
    op.drop_column("order_items", "pricing_mode")

    # orders
    op.drop_index("idx_orders_sales_channel_id", table_name="orders")
    op.drop_column("orders", "serve_duration_min")
    op.drop_column("orders", "served_at")
    op.drop_column("orders", "gross_margin_after")
    op.drop_column("orders", "gross_margin_before")
    op.drop_column("orders", "margin_alert_flag")
    op.drop_column("orders", "discount_type")
    op.drop_column("orders", "abnormal_type")
    op.drop_column("orders", "abnormal_flag")
    op.drop_column("orders", "dining_duration_min")
    op.drop_column("orders", "guest_count")
    op.drop_column("orders", "sales_channel_id")
    op.drop_column("orders", "order_type")
    op.drop_column("orders", "customer_phone")
    op.drop_column("orders", "customer_name")

    # dishes
    op.drop_constraint("fk_dishes_store_id", "dishes", type_="foreignkey")
    op.drop_index("idx_dishes_dish_master_id", table_name="dishes")
    op.drop_index("idx_dishes_store_id", table_name="dishes")
    op.drop_column("dishes", "dish_metadata")
    op.drop_column("dishes", "notes")
    op.drop_column("dishes", "dish_master_id")
    op.drop_column("dishes", "low_stock_threshold")
    op.drop_column("dishes", "requires_inventory")
    op.drop_column("dishes", "season")
    op.drop_column("dishes", "sell_time_ranges")
    op.drop_column("dishes", "sell_end_date")
    op.drop_column("dishes", "sell_start_date")
    op.drop_column("dishes", "production_dept_id")
    op.drop_column("dishes", "store_id")

    # dish_categories
    op.drop_constraint("fk_dish_categories_store_id", "dish_categories", type_="foreignkey")
    op.drop_index("idx_dish_categories_store_id", table_name="dish_categories")
    op.drop_column("dish_categories", "description")
    op.drop_column("dish_categories", "store_id")

    # customers
    op.drop_column("customers", "risk_score")
    op.drop_column("customers", "store_quadrant")
    op.drop_column("customers", "rfm_updated_at")
    op.drop_column("customers", "m_score")
    op.drop_column("customers", "f_score")
    op.drop_column("customers", "r_score")

    # stores
    op.drop_column("stores", "metadata")
    op.drop_column("stores", "shift_type")
    op.drop_column("stores", "settlement_mode")
    op.drop_column("stores", "license_expiry")
    op.drop_column("stores", "last_online_at")
    op.drop_column("stores", "store_level")
    op.drop_column("stores", "operation_mode")
    op.drop_column("stores", "store_tags")
    op.drop_column("stores", "store_category")
    op.drop_column("stores", "business_type")
    op.drop_column("stores", "meal_periods")
    op.drop_column("stores", "rectification_close_rate")
    op.drop_column("stores", "waste_rate_target")
    op.drop_column("stores", "serve_time_limit_min")
    op.drop_column("stores", "turnover_rate_target")
    op.drop_column("stores", "has_physical_seats")
    op.drop_column("stores", "store_type")
    op.drop_column("stores", "is_active")
    op.drop_column("stores", "manager_id")
    op.drop_column("stores", "email")
