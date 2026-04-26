"""v361: forge_builder_projects + forge_builder_templates for Forge v2.5.

可视化Agent构建项目 + Agent脚手架模板。

Revision ID: v361_forge_builder
Revises: v360_forge_evidence_cards
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v361_forge_builder"
down_revision: Union[str, None] = "v360_forge_evidence_cards"
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
    # --- forge_builder_projects ---
    op.create_table(
        "forge_builder_projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.String(50), nullable=False, unique=True),
        sa.Column("developer_id", sa.String(50), nullable=False),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("template_type", sa.String(30), nullable=False),
        sa.Column("canvas", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("generated_code", sa.Text, server_default=""),
        sa.Column("preview_url", sa.String(500)),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "template_type IN ('data_analysis','automation','conversational','monitoring','optimization')",
            name="ck_forge_builder_projects_template_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','building','preview','submitted','archived')",
            name="ck_forge_builder_projects_status",
        ),
    )
    op.create_index(
        "ix_forge_builder_projects_dev_status",
        "forge_builder_projects",
        ["developer_id", "status"],
    )
    _enable_rls("forge_builder_projects")

    # --- forge_builder_templates ---
    op.create_table(
        "forge_builder_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.String(50), nullable=False, unique=True),
        sa.Column("template_type", sa.String(30), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("scaffold_code", sa.Text, nullable=False),
        sa.Column("required_ontology", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("example_config", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("usage_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_builder_templates_type",
        "forge_builder_templates",
        ["template_type"],
    )
    _enable_rls("forge_builder_templates")


def downgrade() -> None:
    _disable_rls("forge_builder_templates")
    op.drop_table("forge_builder_templates")
    _disable_rls("forge_builder_projects")
    op.drop_table("forge_builder_projects")
