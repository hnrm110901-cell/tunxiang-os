"""v311: 补齐 26 张历史表 RLS（关闭 RLS 技术债）

Revision ID: v311
Revises: v310_mv_performance_indexes
Create Date: 2026-05-02

批量操作为 26 张表：
  1. ALTER TABLE ... ENABLE ROW LEVEL SECURITY
  2. CREATE POLICY ... USING (tenant_id = (current_setting('app.tenant_id'))::UUID)

安全策略统一使用 app.tenant_id（项目标准）。
所有操作使用 IF NOT EXISTS 保证幂等。
"""

from alembic import op

revision = "v311"
down_revision = "v310_mv_performance_indexes"
branch_labels = None
depends_on = None

# 26 张待补 RLS 的表
TABLES = [
    "bonus_rules",
    "ceo_cockpit_snapshots",
    "conversion_funnel_daily",
    "customer_journey_timings",
    "daily_scorecards",
    "delivery_disputes",
    "delivery_temperature_logs",
    "dish_co_occurrence",
    "dish_pricing_suggestions",
    "dynamic_pricing_logs",
    "dynamic_pricing_rules",
    "ingredient_location_bindings",
    "inventory_by_location",
    "invoice_ocr_results",
    "procurement_feedback_logs",
    "satisfaction_ratings",
    "stocktake_loss_approvals",
    "stocktake_loss_cases",
    "stocktake_loss_items",
    "stocktake_loss_writeoffs",
    "store_lifecycle_stages",
    "warehouse_locations",
    "warehouse_zones",
    "yield_alerts",
    # 序列表
    "stocktake_loss_case_no_seq",
    "delivery_temperature_logs_default",
]

RLS_POLICY_SQL = """
    CREATE POLICY IF NOT EXISTS {table}_tenant_isolation
    ON {table}
    USING (tenant_id = (current_setting('app.tenant_id'))::UUID)
"""


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            RLS_POLICY_SQL.format(table=table).strip()
        )


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE IF EXISTS {table} DISABLE ROW LEVEL SECURITY")
