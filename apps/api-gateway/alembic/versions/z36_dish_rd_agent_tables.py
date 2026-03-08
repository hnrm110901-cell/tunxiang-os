"""z36 — Phase 10 菜品研发 Agent 数据模型

Dish R&D Intelligence System：
  dish_rd_categories              品类主数据
  dish_rd_ingredients             原料主数据
  dish_rd_suppliers               供应商主数据
  dish_rd_semi_products           半成品/底料
  dish_rd_dishes                  菜品主档
  dish_rd_dish_versions           菜品版本
  dish_rd_idea_projects           立项项目
  dish_rd_recipes                 配方主档
  dish_rd_recipe_versions         配方版本
  dish_rd_recipe_items            配方明细项(BOM)
  dish_rd_sops                    标准工艺
  dish_rd_nutrition_profiles      营养画像
  dish_rd_allergen_profiles       过敏原画像
  dish_rd_cost_models             成本模型
  dish_rd_supply_assessments      供应可行性评估
  dish_rd_pilot_tests             试点项目
  dish_rd_launch_projects         上市项目
  dish_rd_feedbacks               菜品反馈
  dish_rd_retrospective_reports   复盘报告
  dish_rd_agent_logs              Agent执行日志
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = 'z36'
down_revision = 'z35'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── dish_rd_categories ───────────────────────────────────────────
    op.create_table(
        "dish_rd_categories",
        sa.Column("id",         sa.String(36), primary_key=True),
        sa.Column("brand_id",   sa.String(36), nullable=False),
        sa.Column("name",       sa.String(100), nullable=False),
        sa.Column("parent_id",  sa.String(36), nullable=True),
        sa.Column("level",      sa.Integer, default=1),
        sa.Column("sort_order", sa.Integer, default=0),
        sa.Column("is_active",  sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_dish_rd_categories_brand", "dish_rd_categories", ["brand_id"])

    # ── dish_rd_ingredients ──────────────────────────────────────────
    op.create_table(
        "dish_rd_ingredients",
        sa.Column("id",                       sa.String(36), primary_key=True),
        sa.Column("brand_id",                 sa.String(36), nullable=False),
        sa.Column("ingredient_code",          sa.String(50), nullable=False, unique=True),
        sa.Column("ingredient_name",          sa.String(200), nullable=False),
        sa.Column("alias_names",              sa.JSON),
        sa.Column("category_id",             sa.String(36)),
        sa.Column("spec_desc",               sa.String(200)),
        sa.Column("purchase_unit",           sa.String(20), default="kg"),
        sa.Column("usage_unit",              sa.String(20), default="g"),
        sa.Column("unit_convert_ratio",      sa.Float, default=1000.0),
        sa.Column("standard_price",          sa.Numeric(10, 4), default=0),
        sa.Column("loss_rate",               sa.Float, default=0.05),
        sa.Column("seasonality_type",        sa.String(20), default="all_year"),
        sa.Column("season_start_month",      sa.Integer),
        sa.Column("season_end_month",        sa.Integer),
        sa.Column("risk_level",              sa.String(10), default="low"),
        sa.Column("availability_regions",    sa.JSON),
        sa.Column("temperature_type",        sa.String(20), default="ambient"),
        sa.Column("shelf_life_days",         sa.Integer),
        sa.Column("allergen_tags",           sa.JSON),
        sa.Column("nutrition_data",          sa.JSON),
        sa.Column("supplier_ids",            sa.JSON),
        sa.Column("substitute_ingredient_ids", sa.JSON),
        sa.Column("is_active",               sa.Boolean, default=True),
        sa.Column("created_at",              sa.DateTime),
        sa.Column("updated_at",              sa.DateTime),
    )
    op.create_index("ix_dish_rd_ingredients_brand", "dish_rd_ingredients", ["brand_id"])

    # ── dish_rd_suppliers ────────────────────────────────────────────
    op.create_table(
        "dish_rd_suppliers",
        sa.Column("id",                  sa.String(36), primary_key=True),
        sa.Column("brand_id",            sa.String(36), nullable=False),
        sa.Column("supplier_code",       sa.String(50), nullable=False, unique=True),
        sa.Column("supplier_name",       sa.String(200), nullable=False),
        sa.Column("supplier_type",       sa.String(20), default="distributor"),
        sa.Column("region_scope",        sa.JSON),
        sa.Column("delivery_capability", sa.JSON),
        sa.Column("price_level",         sa.String(10), default="medium"),
        sa.Column("stability_score",     sa.Float, default=80.0),
        sa.Column("quality_score",       sa.Float, default=80.0),
        sa.Column("contact_info",        sa.JSON),
        sa.Column("is_active",           sa.Boolean, default=True),
        sa.Column("created_at",          sa.DateTime),
        sa.Column("updated_at",          sa.DateTime),
    )
    op.create_index("ix_dish_rd_suppliers_brand", "dish_rd_suppliers", ["brand_id"])

    # ── dish_rd_semi_products ────────────────────────────────────────
    op.create_table(
        "dish_rd_semi_products",
        sa.Column("id",                         sa.String(36), primary_key=True),
        sa.Column("brand_id",                   sa.String(36), nullable=False),
        sa.Column("semi_code",                  sa.String(50), nullable=False, unique=True),
        sa.Column("semi_name",                  sa.String(200), nullable=False),
        sa.Column("semi_type",                  sa.String(20), default="sauce"),
        sa.Column("recipe_id",                  sa.String(36)),
        sa.Column("current_recipe_version_id",  sa.String(36)),
        sa.Column("standard_cost",              sa.Numeric(10, 4), default=0),
        sa.Column("yield_rate",                 sa.Float, default=1.0),
        sa.Column("storage_type",               sa.String(20), default="chilled"),
        sa.Column("shelf_life_days",            sa.Integer, default=3),
        sa.Column("used_by_dish_ids",           sa.JSON),
        sa.Column("risk_level",                 sa.String(10), default="low"),
        sa.Column("is_active",                  sa.Boolean, default=True),
        sa.Column("created_at",                 sa.DateTime),
    )
    op.create_index("ix_dish_rd_semi_products_brand", "dish_rd_semi_products", ["brand_id"])

    # ── dish_rd_dishes ───────────────────────────────────────────────
    op.create_table(
        "dish_rd_dishes",
        sa.Column("id",                       sa.String(36), primary_key=True),
        sa.Column("brand_id",                 sa.String(36), nullable=False),
        sa.Column("dish_code",                sa.String(50), nullable=False, unique=True),
        sa.Column("dish_name",                sa.String(200), nullable=False),
        sa.Column("dish_alias",               sa.String(200)),
        sa.Column("category_id",              sa.String(36)),
        sa.Column("subcategory_id",           sa.String(36)),
        sa.Column("dish_type",                sa.String(20), default="new"),
        sa.Column("status",                   sa.String(30), default="draft"),
        sa.Column("lifecycle_stage",          sa.String(20), default="insight"),
        sa.Column("positioning_type",         sa.String(20)),
        sa.Column("target_price_yuan",        sa.Numeric(10, 2)),
        sa.Column("target_margin_rate",       sa.Float),
        sa.Column("target_audience",          sa.JSON),
        sa.Column("consumption_scene",        sa.JSON),
        sa.Column("region_scope",             sa.JSON),
        sa.Column("store_scope",              sa.JSON),
        sa.Column("owner_user_id",            sa.String(36)),
        sa.Column("source_type",              sa.String(50), default="initiative"),
        sa.Column("description",              sa.Text),
        sa.Column("highlight_tags",           sa.JSON),
        sa.Column("flavor_tags",              sa.JSON),
        sa.Column("health_tags",              sa.JSON),
        sa.Column("cover_image_url",          sa.String(500)),
        sa.Column("hero_image_urls",          sa.JSON),
        sa.Column("current_version_id",       sa.String(36)),
        sa.Column("latest_recipe_version_id", sa.String(36)),
        sa.Column("current_sop_id",           sa.String(36)),
        sa.Column("created_at",               sa.DateTime),
        sa.Column("updated_at",               sa.DateTime),
        sa.Column("archived_at",              sa.DateTime),
    )
    op.create_index("ix_dish_rd_dishes_brand_status", "dish_rd_dishes", ["brand_id", "status"])

    # ── dish_rd_dish_versions ────────────────────────────────────────
    op.create_table(
        "dish_rd_dish_versions",
        sa.Column("id",                   sa.String(36), primary_key=True),
        sa.Column("dish_id",              sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("version_no",           sa.String(20), nullable=False),
        sa.Column("version_type",         sa.String(20), default="dev"),
        sa.Column("region_id",            sa.String(36)),
        sa.Column("store_level_scope",    sa.JSON),
        sa.Column("recipe_version_id",    sa.String(36)),
        sa.Column("sop_id",               sa.String(36)),
        sa.Column("cost_model_id",        sa.String(36)),
        sa.Column("nutrition_profile_id", sa.String(36)),
        sa.Column("allergen_profile_id",  sa.String(36)),
        sa.Column("supply_assessment_id", sa.String(36)),
        sa.Column("release_status",       sa.String(20), default="unreleased"),
        sa.Column("effective_start_at",   sa.DateTime),
        sa.Column("effective_end_at",     sa.DateTime),
        sa.Column("parent_version_id",    sa.String(36)),
        sa.Column("branch_reason",        sa.String(50)),
        sa.Column("is_current",           sa.Boolean, default=False),
        sa.Column("change_summary",       sa.Text),
        sa.Column("created_by",           sa.String(36)),
        sa.Column("created_at",           sa.DateTime),
    )
    op.create_index("ix_dish_rd_dish_versions_dish", "dish_rd_dish_versions", ["dish_id"])

    # ── dish_rd_idea_projects ────────────────────────────────────────
    op.create_table(
        "dish_rd_idea_projects",
        sa.Column("id",                    sa.String(36), primary_key=True),
        sa.Column("brand_id",              sa.String(36), nullable=False),
        sa.Column("project_code",          sa.String(50), nullable=False, unique=True),
        sa.Column("dish_id",               sa.String(36), sa.ForeignKey("dish_rd_dishes.id")),
        sa.Column("project_name",          sa.String(200), nullable=False),
        sa.Column("project_type",          sa.String(20), default="new"),
        sa.Column("initiation_reason",     sa.Text),
        sa.Column("business_goal",         sa.Text),
        sa.Column("target_launch_date",    sa.Date),
        sa.Column("target_region_scope",   sa.JSON),
        sa.Column("target_store_scope",    sa.JSON),
        sa.Column("target_price_yuan",     sa.Numeric(10, 2)),
        sa.Column("target_margin_rate",    sa.Float),
        sa.Column("sponsor_user_id",       sa.String(36)),
        sa.Column("owner_user_id",         sa.String(36)),
        sa.Column("collaborator_user_ids", sa.JSON),
        sa.Column("priority",              sa.String(10), default="medium"),
        sa.Column("project_status",        sa.String(30), default="pending_approval"),
        sa.Column("approval_status",       sa.String(20), default="pending"),
        sa.Column("risk_level",            sa.String(10), default="low"),
        sa.Column("attachment_urls",       sa.JSON),
        sa.Column("conclusion",            sa.String(20)),
        sa.Column("created_at",            sa.DateTime),
        sa.Column("updated_at",            sa.DateTime),
        sa.Column("closed_at",             sa.DateTime),
    )
    op.create_index("ix_dish_rd_idea_projects_brand", "dish_rd_idea_projects", ["brand_id"])

    # ── dish_rd_recipes ──────────────────────────────────────────────
    op.create_table(
        "dish_rd_recipes",
        sa.Column("id",                 sa.String(36), primary_key=True),
        sa.Column("dish_id",            sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("brand_id",           sa.String(36), nullable=False),
        sa.Column("recipe_code",        sa.String(50), nullable=False, unique=True),
        sa.Column("recipe_name",        sa.String(200), nullable=False),
        sa.Column("recipe_type",        sa.String(20), default="main"),
        sa.Column("current_version_id", sa.String(36)),
        sa.Column("owner_user_id",      sa.String(36)),
        sa.Column("description",        sa.Text),
        sa.Column("created_at",         sa.DateTime),
        sa.Column("updated_at",         sa.DateTime),
    )
    op.create_index("ix_dish_rd_recipes_dish", "dish_rd_recipes", ["dish_id"])

    # ── dish_rd_recipe_versions ──────────────────────────────────────
    op.create_table(
        "dish_rd_recipe_versions",
        sa.Column("id",                   sa.String(36), primary_key=True),
        sa.Column("recipe_id",            sa.String(36), sa.ForeignKey("dish_rd_recipes.id"), nullable=False),
        sa.Column("version_no",           sa.String(20), nullable=False),
        sa.Column("version_type",         sa.String(20), default="dev"),
        sa.Column("status",               sa.String(20), default="draft"),
        sa.Column("parent_version_id",    sa.String(36)),
        sa.Column("change_reason",        sa.String(50)),
        sa.Column("serving_size",         sa.Float, default=1.0),
        sa.Column("serving_unit",         sa.String(20), default="份"),
        sa.Column("yield_rate",           sa.Float, default=1.0),
        sa.Column("loss_rate",            sa.Float, default=0.05),
        sa.Column("prep_time_min",        sa.Integer, default=5),
        sa.Column("cook_time_min",        sa.Integer, default=10),
        sa.Column("complexity_score",     sa.Float, default=3.0),
        sa.Column("difficulty_level",     sa.String(10), default="medium"),
        sa.Column("taste_profile",        sa.JSON),
        sa.Column("texture_profile",      sa.JSON),
        sa.Column("visual_standard_desc", sa.Text),
        sa.Column("notes",                sa.Text),
        sa.Column("approved_by",          sa.String(36)),
        sa.Column("approved_at",          sa.DateTime),
        sa.Column("created_by",           sa.String(36)),
        sa.Column("created_at",           sa.DateTime),
        sa.Column("updated_at",           sa.DateTime),
    )
    op.create_index("ix_dish_rd_recipe_versions_recipe", "dish_rd_recipe_versions", ["recipe_id"])

    # ── dish_rd_recipe_items ─────────────────────────────────────────
    op.create_table(
        "dish_rd_recipe_items",
        sa.Column("id",                   sa.String(36), primary_key=True),
        sa.Column("recipe_version_id",    sa.String(36), sa.ForeignKey("dish_rd_recipe_versions.id"), nullable=False),
        sa.Column("item_type",            sa.String(20), nullable=False),
        sa.Column("item_id",              sa.String(36), nullable=False),
        sa.Column("item_name_snapshot",   sa.String(200), nullable=False),
        sa.Column("quantity",             sa.Float, nullable=False),
        sa.Column("unit",                 sa.String(20), nullable=False),
        sa.Column("loss_rate_snapshot",   sa.Float, default=0.05),
        sa.Column("yield_rate_snapshot",  sa.Float, default=1.0),
        sa.Column("unit_price_snapshot",  sa.Numeric(10, 4), default=0),
        sa.Column("process_stage",        sa.String(20), default="cooking"),
        sa.Column("sequence_no",          sa.Integer, default=1),
        sa.Column("optional_flag",        sa.Boolean, default=False),
        sa.Column("substitute_group_code", sa.String(50)),
        sa.Column("notes",                sa.Text),
        sa.Column("created_at",           sa.DateTime),
    )
    op.create_index("ix_dish_rd_recipe_items_version", "dish_rd_recipe_items", ["recipe_version_id"])

    # ── dish_rd_sops ─────────────────────────────────────────────────
    op.create_table(
        "dish_rd_sops",
        sa.Column("id",                 sa.String(36), primary_key=True),
        sa.Column("dish_id",            sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("dish_version_id",    sa.String(36)),
        sa.Column("brand_id",           sa.String(36), nullable=False),
        sa.Column("sop_code",           sa.String(50), nullable=False, unique=True),
        sa.Column("sop_type",           sa.String(20), default="standard"),
        sa.Column("version_no",         sa.String(20), default="v1"),
        sa.Column("prep_sop",           sa.JSON),
        sa.Column("cook_sop",           sa.JSON),
        sa.Column("plating_sop",        sa.JSON),
        sa.Column("utensil_standard",   sa.JSON),
        sa.Column("output_image_urls",  sa.JSON),
        sa.Column("output_video_urls",  sa.JSON),
        sa.Column("common_errors",      sa.JSON),
        sa.Column("key_points",         sa.JSON),
        sa.Column("training_points",    sa.JSON),
        sa.Column("expected_time_min",  sa.Integer, default=15),
        sa.Column("status",             sa.String(20), default="draft"),
        sa.Column("created_at",         sa.DateTime),
        sa.Column("updated_at",         sa.DateTime),
    )
    op.create_index("ix_dish_rd_sops_dish", "dish_rd_sops", ["dish_id"])

    # ── dish_rd_nutrition_profiles ───────────────────────────────────
    op.create_table(
        "dish_rd_nutrition_profiles",
        sa.Column("id",                 sa.String(36), primary_key=True),
        sa.Column("dish_id",            sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("dish_version_id",    sa.String(36)),
        sa.Column("recipe_version_id",  sa.String(36)),
        sa.Column("calories_kcal",      sa.Float, default=0),
        sa.Column("protein_g",          sa.Float, default=0),
        sa.Column("fat_g",              sa.Float, default=0),
        sa.Column("carb_g",             sa.Float, default=0),
        sa.Column("sugar_g",            sa.Float, default=0),
        sa.Column("sodium_mg",          sa.Float, default=0),
        sa.Column("fiber_g",            sa.Float, default=0),
        sa.Column("nutrition_tags",     sa.JSON),
        sa.Column("calculated_at",      sa.DateTime),
    )
    op.create_index("ix_dish_rd_nutrition_profiles_dish", "dish_rd_nutrition_profiles", ["dish_id"])

    # ── dish_rd_allergen_profiles ────────────────────────────────────
    op.create_table(
        "dish_rd_allergen_profiles",
        sa.Column("id",                sa.String(36), primary_key=True),
        sa.Column("dish_id",           sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("dish_version_id",   sa.String(36)),
        sa.Column("recipe_version_id", sa.String(36)),
        sa.Column("allergen_tags",     sa.JSON),
        sa.Column("risk_level",        sa.String(10), default="low"),
        sa.Column("warnings",          sa.JSON),
        sa.Column("calculated_at",     sa.DateTime),
    )
    op.create_index("ix_dish_rd_allergen_profiles_dish", "dish_rd_allergen_profiles", ["dish_id"])

    # ── dish_rd_cost_models ──────────────────────────────────────────
    op.create_table(
        "dish_rd_cost_models",
        sa.Column("id",                       sa.String(36), primary_key=True),
        sa.Column("dish_id",                  sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("dish_version_id",          sa.String(36)),
        sa.Column("recipe_version_id",        sa.String(36)),
        sa.Column("brand_id",                 sa.String(36), nullable=False),
        sa.Column("calculation_basis",        sa.String(30), default="theoretical"),
        sa.Column("ingredient_cost_total",    sa.Numeric(10, 4), default=0),
        sa.Column("semi_product_cost_total",  sa.Numeric(10, 4), default=0),
        sa.Column("packaging_cost_total",     sa.Numeric(10, 4), default=0),
        sa.Column("garnish_cost_total",       sa.Numeric(10, 4), default=0),
        sa.Column("labor_cost_estimate",      sa.Numeric(10, 4), default=0),
        sa.Column("utility_cost_estimate",    sa.Numeric(10, 4), default=0),
        sa.Column("total_cost",               sa.Numeric(10, 4), default=0),
        sa.Column("suggested_price_yuan",     sa.Numeric(10, 2), default=0),
        sa.Column("margin_amount_yuan",       sa.Numeric(10, 2), default=0),
        sa.Column("margin_rate",              sa.Float, default=0),
        sa.Column("price_scenarios",          sa.JSON),
        sa.Column("item_details",             sa.JSON),
        sa.Column("calculation_version",      sa.String(20), default="v1"),
        sa.Column("calculated_at",            sa.DateTime),
        sa.Column("calculated_by",            sa.String(36)),
    )
    op.create_index("ix_dish_rd_cost_models_dish", "dish_rd_cost_models", ["dish_id"])

    # ── dish_rd_supply_assessments ───────────────────────────────────
    op.create_table(
        "dish_rd_supply_assessments",
        sa.Column("id",                              sa.String(36), primary_key=True),
        sa.Column("dish_id",                         sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("dish_version_id",                 sa.String(36)),
        sa.Column("brand_id",                        sa.String(36), nullable=False),
        sa.Column("region_scope",                    sa.JSON),
        sa.Column("supplier_coverage_rate",          sa.Float, default=0),
        sa.Column("ingredient_availability_score",   sa.Float, default=0),
        sa.Column("cold_chain_score",                sa.Float, default=0),
        sa.Column("seasonality_risk_score",          sa.Float, default=0),
        sa.Column("substitution_feasibility_score",  sa.Float, default=0),
        sa.Column("total_supply_score",              sa.Float, default=0),
        sa.Column("supply_risk_level",               sa.String(10), default="medium"),
        sa.Column("restriction_notes",               sa.Text),
        sa.Column("recommendation",                  sa.String(20), default="regional"),
        sa.Column("assessed_at",                     sa.DateTime),
        sa.Column("assessed_by",                     sa.String(36)),
    )
    op.create_index("ix_dish_rd_supply_assessments_dish", "dish_rd_supply_assessments", ["dish_id"])

    # ── dish_rd_pilot_tests ──────────────────────────────────────────
    op.create_table(
        "dish_rd_pilot_tests",
        sa.Column("id",                          sa.String(36), primary_key=True),
        sa.Column("pilot_code",                  sa.String(50), nullable=False, unique=True),
        sa.Column("dish_id",                     sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("brand_id",                    sa.String(36), nullable=False),
        sa.Column("dish_version_id",             sa.String(36)),
        sa.Column("recipe_version_id",           sa.String(36)),
        sa.Column("target_store_ids",            sa.JSON),
        sa.Column("start_date",                  sa.Date),
        sa.Column("end_date",                    sa.Date),
        sa.Column("pilot_goal",                  sa.JSON),
        sa.Column("pilot_status",                sa.String(20), default="pending"),
        sa.Column("store_feedback_summary",      sa.JSON),
        sa.Column("avg_taste_score",             sa.Float),
        sa.Column("avg_operation_score",         sa.Float),
        sa.Column("avg_sales_score",             sa.Float),
        sa.Column("avg_margin_score",            sa.Float),
        sa.Column("avg_customer_feedback_score", sa.Float),
        sa.Column("decision",                    sa.String(10)),
        sa.Column("decision_reason",             sa.Text),
        sa.Column("report_url",                  sa.String(500)),
        sa.Column("created_at",                  sa.DateTime),
        sa.Column("updated_at",                  sa.DateTime),
    )
    op.create_index("ix_dish_rd_pilot_tests_dish", "dish_rd_pilot_tests", ["dish_id"])

    # ── dish_rd_launch_projects ──────────────────────────────────────
    op.create_table(
        "dish_rd_launch_projects",
        sa.Column("id",                         sa.String(36), primary_key=True),
        sa.Column("launch_code",                sa.String(50), nullable=False, unique=True),
        sa.Column("dish_id",                    sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("brand_id",                   sa.String(36), nullable=False),
        sa.Column("dish_version_id",            sa.String(36)),
        sa.Column("launch_scope",               sa.JSON),
        sa.Column("launch_type",                sa.String(20), default="regional"),
        sa.Column("planned_launch_date",        sa.Date),
        sa.Column("actual_launch_date",         sa.Date),
        sa.Column("checklist_status",           sa.String(20), default="incomplete"),
        sa.Column("approval_status",            sa.String(20), default="pending"),
        sa.Column("training_package_status",    sa.String(20), default="not_sent"),
        sa.Column("procurement_package_status", sa.String(20), default="not_sent"),
        sa.Column("operation_notice_status",    sa.String(20), default="not_sent"),
        sa.Column("launch_status",              sa.String(20), default="pending"),
        sa.Column("launched_store_count",       sa.Integer, default=0),
        sa.Column("abnormal_store_count",       sa.Integer, default=0),
        sa.Column("rollback_reason",            sa.Text),
        sa.Column("created_at",                 sa.DateTime),
        sa.Column("updated_at",                 sa.DateTime),
    )
    op.create_index("ix_dish_rd_launch_projects_dish", "dish_rd_launch_projects", ["dish_id"])

    # ── dish_rd_feedbacks ────────────────────────────────────────────
    op.create_table(
        "dish_rd_feedbacks",
        sa.Column("id",              sa.String(36), primary_key=True),
        sa.Column("dish_id",         sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("brand_id",        sa.String(36), nullable=False),
        sa.Column("dish_version_id", sa.String(36)),
        sa.Column("feedback_source", sa.String(20), default="manager"),
        sa.Column("feedback_type",   sa.String(20), default="taste"),
        sa.Column("source_ref_id",   sa.String(36)),
        sa.Column("rating_score",    sa.Float),
        sa.Column("keyword_tags",    sa.JSON),
        sa.Column("content",         sa.Text),
        sa.Column("store_id",        sa.String(36)),
        sa.Column("region_id",       sa.String(36)),
        sa.Column("happened_at",     sa.DateTime),
        sa.Column("severity_level",  sa.String(10), default="low"),
        sa.Column("handled_status",  sa.String(20), default="pending"),
        sa.Column("created_at",      sa.DateTime),
    )
    op.create_index("ix_dish_rd_feedbacks_dish_type", "dish_rd_feedbacks", ["dish_id", "feedback_type"])
    op.create_index("ix_dish_rd_feedbacks_brand",     "dish_rd_feedbacks", ["brand_id"])

    # ── dish_rd_retrospective_reports ────────────────────────────────
    op.create_table(
        "dish_rd_retrospective_reports",
        sa.Column("id",                       sa.String(36), primary_key=True),
        sa.Column("dish_id",                  sa.String(36), sa.ForeignKey("dish_rd_dishes.id"), nullable=False),
        sa.Column("brand_id",                 sa.String(36), nullable=False),
        sa.Column("dish_version_id",          sa.String(36)),
        sa.Column("retrospective_period",     sa.String(20), default="30d"),
        sa.Column("sales_summary",            sa.JSON),
        sa.Column("margin_summary",           sa.JSON),
        sa.Column("return_reason_summary",    sa.JSON),
        sa.Column("feedback_summary",         sa.JSON),
        sa.Column("execution_summary",        sa.JSON),
        sa.Column("lifecycle_assessment",     sa.String(20)),
        sa.Column("optimization_suggestions", sa.JSON),
        sa.Column("conclusion",               sa.Text),
        sa.Column("generated_by",             sa.String(36)),
        sa.Column("generated_at",             sa.DateTime),
    )
    op.create_index("ix_dish_rd_retrospective_reports_dish", "dish_rd_retrospective_reports", ["dish_id"])

    # ── dish_rd_agent_logs ───────────────────────────────────────────
    op.create_table(
        "dish_rd_agent_logs",
        sa.Column("id",             sa.String(36), primary_key=True),
        sa.Column("dish_id",        sa.String(36)),
        sa.Column("brand_id",       sa.String(36), nullable=False),
        sa.Column("agent_type",     sa.String(30), nullable=False),
        sa.Column("trigger_reason", sa.String(200)),
        sa.Column("input_data",     sa.JSON),
        sa.Column("output_data",    sa.JSON),
        sa.Column("recommendation", sa.Text),
        sa.Column("confidence",     sa.Float, default=0.8),
        sa.Column("executed_at",    sa.DateTime),
        sa.Column("executed_by",    sa.String(36)),
    )
    op.create_index("ix_dish_rd_agent_logs_brand", "dish_rd_agent_logs", ["brand_id"])


def downgrade() -> None:
    for table in [
        "dish_rd_agent_logs",
        "dish_rd_retrospective_reports",
        "dish_rd_feedbacks",
        "dish_rd_launch_projects",
        "dish_rd_pilot_tests",
        "dish_rd_supply_assessments",
        "dish_rd_cost_models",
        "dish_rd_allergen_profiles",
        "dish_rd_nutrition_profiles",
        "dish_rd_sops",
        "dish_rd_recipe_items",
        "dish_rd_recipe_versions",
        "dish_rd_recipes",
        "dish_rd_idea_projects",
        "dish_rd_dish_versions",
        "dish_rd_dishes",
        "dish_rd_semi_products",
        "dish_rd_suppliers",
        "dish_rd_ingredients",
        "dish_rd_categories",
    ]:
        op.drop_table(table)
