"""v350: forge_installations table for tx-forge microservice.

Revision ID: v350_forge_installations
Revises: v349_forge_reviews
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v350_forge_installations"
down_revision: Union[str, None] = "v349_forge_reviews"
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
        "forge_installations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("install_id", sa.String(50), unique=True),
        sa.Column("app_id", sa.String(50)),
        sa.Column("store_ids", sa.dialects.postgresql.JSONB, server_default="[]"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("installed_version", sa.String(50)),
        sa.Column("config", sa.dialects.postgresql.JSONB, server_default="{}"),
        sa.Column("installed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("uninstalled_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "status IN ('active','uninstalled','suspended')",
            name="ck_forge_installations_status",
        ),
        sa.UniqueConstraint("tenant_id", "app_id", name="uq_forge_installations_tenant_app"),
    )
    op.create_index("ix_forge_installations_tenant_status", "forge_installations", ["tenant_id", "status"])
    op.create_index("ix_forge_installations_app_status", "forge_installations", ["app_id", "status"])
    _enable_rls("forge_installations")


def downgrade() -> None:
    _disable_rls("forge_installations")
    op.drop_table("forge_installations")
