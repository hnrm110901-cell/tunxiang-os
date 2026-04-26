"""v356: forge_ontology_bindings + forge_manifest_versions tables for Forge v1.5 治理地基.

Revision ID: v356_forge_ontology_manifests
Revises: v355_forge_mcp_registry
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v356_forge_ontology_manifests"
down_revision: Union[str, None] = "v355_forge_mcp_registry"
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
    # --- forge_ontology_bindings ---
    op.create_table(
        "forge_ontology_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("entity_name", sa.String(50), nullable=False),
        sa.Column("access_mode", sa.String(10), nullable=False),
        sa.Column("allowed_fields", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("constraints", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("app_id", "entity_name", name="uq_forge_ontology_bindings_app_entity"),
        sa.CheckConstraint(
            "access_mode IN ('read','write','read_write')",
            name="ck_forge_ontology_bindings_access_mode",
        ),
    )
    op.create_index(
        "ix_forge_ontology_bindings_entity_access",
        "forge_ontology_bindings",
        ["entity_name", "access_mode"],
    )
    _enable_rls("forge_ontology_bindings")

    # --- forge_manifest_versions ---
    op.create_table(
        "forge_manifest_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("forge_version", sa.String(20), nullable=False, server_default="1.5"),
        sa.Column("manifest_content", sa.JSON, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("validated", sa.Boolean, server_default=sa.text("false")),
        sa.Column("validation_errors", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_manifest_versions_app_submitted",
        "forge_manifest_versions",
        ["app_id", sa.text("submitted_at DESC")],
    )
    _enable_rls("forge_manifest_versions")


def downgrade() -> None:
    _disable_rls("forge_manifest_versions")
    op.drop_table("forge_manifest_versions")
    _disable_rls("forge_ontology_bindings")
    op.drop_table("forge_ontology_bindings")
