"""v352: forge_revenue_entries (append-only) + forge_payouts tables for tx-forge microservice.

Revision ID: v352_forge_revenue_payouts
Revises: v351_forge_sandboxes
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v352_forge_revenue_payouts"
down_revision: Union[str, None] = "v351_forge_sandboxes"
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


def _enable_rls_readonly(table_name: str) -> None:
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
    # --- forge_revenue_entries (append-only) ---
    op.create_table(
        "forge_revenue_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50)),
        sa.Column("payer_tenant_id", UUID(as_uuid=True)),
        sa.Column("amount_fen", sa.BigInteger),
        sa.Column("platform_fee_fen", sa.BigInteger),
        sa.Column("developer_payout_fen", sa.BigInteger),
        sa.Column("fee_rate", sa.Numeric(5, 4)),
        sa.Column("pricing_model", sa.String(20)),
        sa.Column("description", sa.String(500), server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_revenue_entries_app_created",
        "forge_revenue_entries",
        ["app_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_forge_revenue_entries_tenant_created",
        "forge_revenue_entries",
        ["tenant_id", sa.text("created_at DESC")],
    )
    _enable_rls_readonly("forge_revenue_entries")

    # --- forge_payouts ---
    op.create_table(
        "forge_payouts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("payout_id", sa.String(50), unique=True),
        sa.Column("developer_id", sa.String(50)),
        sa.Column("amount_fen", sa.BigInteger),
        sa.Column("bank_account", sa.String(200)),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("failure_reason", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint("amount_fen > 0", name="ck_forge_payouts_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="ck_forge_payouts_status",
        ),
    )
    op.create_index("ix_forge_payouts_developer_status", "forge_payouts", ["developer_id", "status"])
    _enable_rls("forge_payouts")


def downgrade() -> None:
    _disable_rls("forge_payouts")
    op.drop_table("forge_payouts")
    _disable_rls("forge_revenue_entries")
    op.drop_table("forge_revenue_entries")
