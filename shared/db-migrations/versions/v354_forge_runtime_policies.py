"""v354: forge_runtime_policies + forge_runtime_violations tables for Forge v1.5 治理地基.

Revision ID: v354_forge_runtime_policies
Revises: v353_forge_trust_system
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v354_forge_runtime_policies"
down_revision: Union[str, None] = "v353_forge_trust_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _enable_rls_append_only(table_name: str) -> None:
    """Append-only RLS: SELECT + INSERT only, no UPDATE/DELETE policies."""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # --- forge_runtime_policies ---
    op.create_table(
        "forge_runtime_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False, unique=True),
        sa.Column("trust_tier", sa.String(10), nullable=False, server_default="T0"),
        sa.Column("allowed_entities", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("allowed_actions", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("denied_actions", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("token_budget_daily", sa.Integer, server_default="100000"),
        sa.Column("rate_limit_rpm", sa.Integer, server_default="60"),
        sa.Column("kill_switch", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sandbox_mode", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("auto_downgrade_threshold", sa.Integer, server_default="3"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_runtime_policies_trust_tier",
        "forge_runtime_policies",
        ["trust_tier"],
    )
    op.create_index(
        "ix_forge_runtime_policies_kill_switch",
        "forge_runtime_policies",
        ["kill_switch"],
        postgresql_where=sa.text("kill_switch = true"),
    )
    _enable_rls("forge_runtime_policies")

    # --- forge_runtime_violations (append-only) ---
    op.create_table(
        "forge_runtime_violations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("agent_id", sa.String(100)),
        sa.Column("violation_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False, server_default="P2"),
        sa.Column("context", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved", sa.Boolean, server_default=sa.text("false")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolved_by", sa.String(100)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "violation_type IN ('permission_denied','token_exceeded','rate_limited',"
            "'constraint_violated','kill_switched','data_boundary','action_blocked')",
            name="ck_forge_runtime_violations_type",
        ),
        sa.CheckConstraint(
            "severity IN ('P0','P1','P2','P3')",
            name="ck_forge_runtime_violations_severity",
        ),
    )
    op.create_index(
        "ix_forge_runtime_violations_app_created",
        "forge_runtime_violations",
        ["app_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_forge_runtime_violations_severity_resolved",
        "forge_runtime_violations",
        ["severity", "resolved"],
    )
    _enable_rls_append_only("forge_runtime_violations")


def downgrade() -> None:
    _disable_rls("forge_runtime_violations")
    op.drop_table("forge_runtime_violations")
    _disable_rls("forge_runtime_policies")
    op.drop_table("forge_runtime_policies")
