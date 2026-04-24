"""v014: Fix insecure RLS on v013 banquet tables

v013 used the old v001-v005 RLS pattern which has three vulnerabilities:
  1. No NULL/empty guard on current_setting → potential bypass
  2. Missing UPDATE/DELETE policies → unrestricted modifications
  3. Missing FORCE ROW LEVEL SECURITY → table owner bypasses all policies

This migration applies the same fix pattern as v006 to the 4 tables
created in v013: banquet_proposals, banquet_quotations, banquet_feedbacks,
banquet_cases.

Revision ID: v014
Revises: v013
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op

revision = "v014"
down_revision= "v013"
branch_labels= None
depends_on= None

V013_TABLES = ["banquet_proposals", "banquet_quotations", "banquet_feedbacks", "banquet_cases"]

_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    for table in V013_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")

        op.execute(
            f"CREATE POLICY {table}_rls_select ON {table} "
            f"FOR SELECT USING ({_SAFE_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_insert ON {table} "
            f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_update ON {table} "
            f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_delete ON {table} "
            f"FOR DELETE USING ({_SAFE_CONDITION})"
        )

        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in V013_TABLES:
        for op_suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{op_suffix} ON {table}")

        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
        op.execute(
            f"CREATE POLICY tenant_insert_{table} ON {table} "
            f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
