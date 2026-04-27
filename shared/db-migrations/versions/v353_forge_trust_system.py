"""v353: forge_trust_tiers + forge_trust_audits tables for Forge v1.5 治理地基.

Revision ID: v353_forge_trust_system
Revises: v352_forge_revenue_payouts
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v353_forge_trust_system"
down_revision: Union[str, None] = "v352_forge_revenue_payouts"
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


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # --- forge_trust_tiers ---
    op.create_table(
        "forge_trust_tiers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tier_code", sa.String(10), nullable=False, unique=True),
        sa.Column("tier_name", sa.String(50), nullable=False),
        sa.Column("data_access", sa.String(20), nullable=False),
        sa.Column("action_scope", sa.String(20), nullable=False),
        sa.Column("financial_access", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("requirements", sa.Text, server_default=""),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    _enable_rls("forge_trust_tiers")

    # --- forge_trust_audits ---
    op.create_table(
        "forge_trust_audits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("previous_tier", sa.String(10)),
        sa.Column("new_tier", sa.String(10), nullable=False),
        sa.Column("audit_type", sa.String(20), nullable=False),
        sa.Column("auditor_id", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text, server_default=""),
        sa.Column("evidence", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("audited_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "audit_type IN ('upgrade','downgrade','initial','suspend')",
            name="ck_forge_trust_audits_audit_type",
        ),
    )
    op.create_index(
        "ix_forge_trust_audits_app_audited",
        "forge_trust_audits",
        ["app_id", sa.text("audited_at DESC")],
    )
    _enable_rls("forge_trust_audits")


def downgrade() -> None:
    _disable_rls("forge_trust_audits")
    op.drop_table("forge_trust_audits")
    _disable_rls("forge_trust_tiers")
    op.drop_table("forge_trust_tiers")
