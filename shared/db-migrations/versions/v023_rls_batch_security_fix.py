"""v023: Batch RLS security fix for v018-v021 tables

Fixes RLS vulnerabilities in tables created by v018-v021:
  - table_production_plans (v018): NULLIF pattern → explicit IS NOT NULL guard
  - cook_time_baselines (v019): NULLIF pattern → explicit IS NOT NULL guard
  - dispatch_rules (v020): NULLIF + missing UPDATE WITH CHECK → full safe pattern
  - shift_configs (v021): missing FORCE + missing NULL guard + single policy → full 4-op safe pattern

All policies unified to v006+ standard:
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v023
Revises: v022b
Create Date: 2026-03-30
"""

from alembic import op

revision = "v023"
down_revision = "v022b"
branch_labels = None
depends_on = None

TABLES_TO_FIX = {
    "table_production_plans": {
        "old_policies": [
            "table_production_plans_tenant_select",
            "table_production_plans_tenant_insert",
            "table_production_plans_tenant_update",
            "table_production_plans_tenant_delete",
        ],
    },
    "cook_time_baselines": {
        "old_policies": [
            "cook_time_baselines_tenant_select",
            "cook_time_baselines_tenant_insert",
            "cook_time_baselines_tenant_update",
            "cook_time_baselines_tenant_delete",
        ],
    },
    "dispatch_rules": {
        "old_policies": [
            "dispatch_rules_select",
            "dispatch_rules_insert",
            "dispatch_rules_update",
            "dispatch_rules_delete",
        ],
    },
    "shift_configs": {
        "old_policies": [
            "shift_configs_tenant_isolation",
        ],
    },
}

_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    for table, info in TABLES_TO_FIX.items():
        for policy_name in info["old_policies"]:
            op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table}")

        op.execute(f"CREATE POLICY {table}_rls_select ON {table} FOR SELECT USING ({_SAFE_CONDITION})")
        op.execute(f"CREATE POLICY {table}_rls_insert ON {table} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
        op.execute(
            f"CREATE POLICY {table}_rls_update ON {table} "
            f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
        )
        op.execute(f"CREATE POLICY {table}_rls_delete ON {table} FOR DELETE USING ({_SAFE_CONDITION})")

        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES_TO_FIX:
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
