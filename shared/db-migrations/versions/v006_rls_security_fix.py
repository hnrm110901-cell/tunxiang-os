"""v006: RLS security fix -- NULL bypass + missing UPDATE/DELETE + FORCE RLS

Fixes three security issues inherited from v001-v005 RLS pattern:

CRITICAL-001 (NULL bypass):
    When app.tenant_id is not set, current_setting('app.tenant_id') returns NULL.
    The expression `tenant_id = NULL::UUID` evaluates to NULL (not TRUE/FALSE),
    which PostgreSQL RLS treats as "deny". However, if the GUC is set to empty
    string '', the cast `''::UUID` will throw an error in some paths or may
    behave unpredictably. We add explicit NOT NULL + non-empty guards.

CRITICAL-002 (incomplete policy coverage):
    v001-v005 only created SELECT (USING) and INSERT (WITH CHECK) policies.
    UPDATE and DELETE operations have no RLS policy, meaning they may be
    unrestricted depending on PostgreSQL version and default policy behavior.
    We add explicit UPDATE and DELETE policies.

CRITICAL-003 (table owner bypass):
    Without FORCE ROW LEVEL SECURITY, the table owner role bypasses all RLS
    policies. If the application connects as the table owner (common in
    single-role setups), RLS is effectively disabled.

Fix approach:
    1. Drop all existing tenant_isolation_* and tenant_insert_* policies
    2. Recreate with safe 4-operation policies (SELECT/INSERT/UPDATE/DELETE)
    3. Add NOT NULL + non-empty guard on all policies
    4. Enable FORCE ROW LEVEL SECURITY on all tables

Revision ID: v006
Revises: v005
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v006"
down_revision: Union[str, None] = "v005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables that have RLS enabled across v001-v005
ALL_RLS_TABLES = [
    # v001 tables
    "customers", "stores", "dish_categories", "dishes", "dish_ingredients",
    "orders", "order_items", "ingredient_masters", "ingredients",
    "ingredient_transactions", "employees",
    # v002 tables
    "tables", "payments", "refunds", "settlements", "shift_handovers",
    "receipt_templates", "receipt_logs", "production_depts", "dish_dept_mappings",
    "daily_ops_flows", "daily_ops_nodes", "agent_decision_logs",
    # v003 tables
    "payment_records", "reconciliation_batches", "reconciliation_diffs",
    "tri_reconciliation_records", "store_daily_settlements", "payment_fees",
    # v004 tables
    "reservations", "queues", "banquet_halls", "banquet_leads",
    "banquet_orders", "banquet_contracts", "menu_packages", "banquet_checklists",
    # v005 tables
    "attendance_rules", "clock_records", "daily_attendance",
    "payroll_batches", "payroll_items", "leave_requests",
    "leave_balances", "settlement_records",
]

# Safe USING / WITH CHECK condition:
# 1. tenant_id must equal the session variable
# 2. Session variable must be set (NOT NULL)
# 3. Session variable must be non-empty
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    """Fix RLS policies: add NULL guard, complete operation coverage, force RLS."""

    for table in ALL_RLS_TABLES:
        # --- 1. Drop old incomplete policies from v001-v005 ---
        # v001-v005 used these naming patterns:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")

        # --- 2. Create safe 4-operation policies ---
        # SELECT
        op.execute(
            f"CREATE POLICY {table}_rls_select ON {table} "
            f"FOR SELECT USING ({_SAFE_CONDITION})"
        )

        # INSERT
        op.execute(
            f"CREATE POLICY {table}_rls_insert ON {table} "
            f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
        )

        # UPDATE (was missing in v001-v005)
        op.execute(
            f"CREATE POLICY {table}_rls_update ON {table} "
            f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
        )

        # DELETE (was missing in v001-v005)
        op.execute(
            f"CREATE POLICY {table}_rls_delete ON {table} "
            f"FOR DELETE USING ({_SAFE_CONDITION})"
        )

        # --- 3. Ensure RLS is enabled AND forced (even for table owner) ---
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Revert to v001-v005 policy pattern (WARNING: re-introduces vulnerabilities)."""

    for table in ALL_RLS_TABLES:
        # Drop the new safe policies
        for op_suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{op_suffix} ON {table}")

        # Remove FORCE (revert to normal RLS)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        # Restore the original v001-v005 style policies
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
        op.execute(
            f"CREATE POLICY tenant_insert_{table} ON {table} "
            f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
