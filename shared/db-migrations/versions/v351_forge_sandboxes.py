"""v351: forge_sandboxes table for tx-forge microservice.

Revision ID: v351_forge_sandboxes
Revises: v350_forge_installations
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v351_forge_sandboxes"
down_revision: Union[str, None] = "v350_forge_installations"
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
    op.create_table(
        "forge_sandboxes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_id", sa.String(50), unique=True),
        sa.Column("developer_id", sa.String(50)),
        sa.Column("app_id", sa.String(50)),
        sa.Column("sandbox_url", sa.String(500)),
        sa.Column("test_tenant_id", sa.String(50)),
        sa.Column("test_api_key_hash", sa.String(128)),
        sa.Column("status", sa.String(20), server_default="running"),
        sa.Column("test_data", sa.dialects.postgresql.JSONB, server_default="{}"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "status IN ('running','stopped','deleted','expired')",
            name="ck_forge_sandboxes_status",
        ),
    )
    op.create_index("ix_forge_sandboxes_developer_status", "forge_sandboxes", ["developer_id", "status"])
    _enable_rls("forge_sandboxes")


def downgrade() -> None:
    _disable_rls("forge_sandboxes")
    op.drop_table("forge_sandboxes")
