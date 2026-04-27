"""v347: forge_developers + forge_api_keys tables for tx-forge microservice.

Revision ID: v347_forge_developers_api_keys
Revises: v346_stored_value_settlement
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v347_forge_developers_api_keys"
down_revision: Union[str, None] = "v346_stored_value_settlement"
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
    # --- forge_developers ---
    op.create_table(
        "forge_developers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("developer_id", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("email", sa.String(200)),
        sa.Column("company", sa.String(200)),
        sa.Column("dev_type", sa.String(20)),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column("website", sa.String(500)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint("dev_type IN ('individual','company','isv')", name="ck_forge_developers_dev_type"),
        sa.CheckConstraint("status IN ('active','verified','suspended')", name="ck_forge_developers_status"),
    )
    op.create_index("ix_forge_developers_tenant_status", "forge_developers", ["tenant_id", "status"])
    op.create_index(
        "ix_forge_developers_email_unique",
        "forge_developers",
        ["email"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    _enable_rls("forge_developers")

    # --- forge_api_keys ---
    op.create_table(
        "forge_api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("key_id", sa.String(50), unique=True, nullable=False),
        sa.Column("developer_id", sa.String(50), nullable=False),
        sa.Column("key_name", sa.String(200)),
        sa.Column("api_key_hash", sa.String(128)),
        sa.Column("api_key_prefix", sa.String(16)),
        sa.Column("permissions", sa.dialects.postgresql.JSONB, server_default='["read"]'),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("usage_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_forge_api_keys_status"),
    )
    op.create_index("ix_forge_api_keys_developer_status", "forge_api_keys", ["developer_id", "status"])
    _enable_rls("forge_api_keys")


def downgrade() -> None:
    _disable_rls("forge_api_keys")
    op.drop_table("forge_api_keys")
    _disable_rls("forge_developers")
    op.drop_table("forge_developers")
