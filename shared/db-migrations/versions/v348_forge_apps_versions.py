"""v348: forge_apps + forge_app_versions tables for tx-forge microservice.

Revision ID: v348_forge_apps_versions
Revises: v347_forge_developers_api_keys
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v348_forge_apps_versions"
down_revision: Union[str, None] = "v347_forge_developers_api_keys"
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
    # --- forge_apps ---
    op.create_table(
        "forge_apps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), unique=True),
        sa.Column("developer_id", sa.String(50)),
        sa.Column("app_name", sa.String(200)),
        sa.Column("category", sa.String(50)),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("icon_url", sa.String(500)),
        sa.Column("screenshots", sa.dialects.postgresql.JSONB, server_default="[]"),
        sa.Column("pricing_model", sa.String(20), server_default="free"),
        sa.Column("price_fen", sa.Integer, server_default=sa.text("0")),
        sa.Column("price_display", sa.String(100)),
        sa.Column("permissions", sa.dialects.postgresql.JSONB, server_default="[]"),
        sa.Column("api_endpoints", sa.dialects.postgresql.JSONB, server_default="[]"),
        sa.Column("webhook_urls", sa.dialects.postgresql.JSONB, server_default="[]"),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("current_version", sa.String(50)),
        sa.Column("rating", sa.Numeric(3, 2), server_default=sa.text("0")),
        sa.Column("rating_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("install_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("revenue_total_fen", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "pricing_model IN ('free','one_time','monthly','per_store','usage_based','freemium')",
            name="ck_forge_apps_pricing_model",
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','needs_changes','published','suspended','deprecated')",
            name="ck_forge_apps_status",
        ),
    )
    op.create_index("ix_forge_apps_tenant_category_status", "forge_apps", ["tenant_id", "category", "status"])
    op.create_index("ix_forge_apps_developer_id", "forge_apps", ["developer_id"])
    op.create_index(
        "ix_forge_apps_status_install_count",
        "forge_apps",
        ["status", sa.text("install_count DESC")],
    )
    _enable_rls("forge_apps")

    # --- forge_app_versions ---
    op.create_table(
        "forge_app_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50)),
        sa.Column("version", sa.String(50)),
        sa.Column("changelog", sa.Text),
        sa.Column("package_url", sa.String(500)),
        sa.Column("package_hash", sa.String(128)),
        sa.Column("min_platform_version", sa.String(20)),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("app_id", "version", name="uq_forge_app_versions_app_version"),
    )
    op.create_index(
        "ix_forge_app_versions_app_created",
        "forge_app_versions",
        ["app_id", sa.text("created_at DESC")],
    )
    _enable_rls("forge_app_versions")


def downgrade() -> None:
    _disable_rls("forge_app_versions")
    op.drop_table("forge_app_versions")
    _disable_rls("forge_apps")
    op.drop_table("forge_apps")
