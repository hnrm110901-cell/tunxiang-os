"""v355: forge_mcp_servers + forge_mcp_tools tables for Forge v1.5 治理地基.

Revision ID: v355_forge_mcp_registry
Revises: v354_forge_runtime_policies
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v355_forge_mcp_registry"
down_revision: Union[str, None] = "v354_forge_runtime_policies"
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
    # --- forge_mcp_servers ---
    op.create_table(
        "forge_mcp_servers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("server_name", sa.String(200), nullable=False),
        sa.Column("transport", sa.String(30), nullable=False, server_default="streamable-http"),
        sa.Column("base_url", sa.String(500)),
        sa.Column("capabilities", sa.JSON, nullable=False, server_default=sa.text(
            "'{\"tools\":[],\"resources\":[],\"prompts\":[]}'::jsonb"
        )),
        sa.Column("schema_version", sa.String(20), server_default="2025-03-26"),
        sa.Column("health_endpoint", sa.String(500)),
        sa.Column("health_status", sa.String(20), server_default="unknown"),
        sa.Column("last_health_check", sa.TIMESTAMP(timezone=True)),
        sa.Column("auto_discovery", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "transport IN ('stdio','sse','streamable-http')",
            name="ck_forge_mcp_servers_transport",
        ),
        sa.CheckConstraint(
            "health_status IN ('healthy','degraded','down','unknown')",
            name="ck_forge_mcp_servers_health_status",
        ),
    )
    op.create_index(
        "ix_forge_mcp_servers_app_id",
        "forge_mcp_servers",
        ["app_id"],
    )
    op.create_index(
        "ix_forge_mcp_servers_health_status",
        "forge_mcp_servers",
        ["health_status"],
    )
    _enable_rls("forge_mcp_servers")

    # --- forge_mcp_tools ---
    op.create_table(
        "forge_mcp_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tool_id", sa.String(50), nullable=False, unique=True),
        sa.Column("server_id", sa.String(50), nullable=False),
        sa.Column("tool_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("input_schema", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_schema", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ontology_bindings", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("trust_tier_required", sa.String(10), server_default="T1"),
        sa.Column("call_count", sa.BigInteger, server_default="0"),
        sa.Column("avg_latency_ms", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_mcp_tools_server_id",
        "forge_mcp_tools",
        ["server_id"],
    )
    op.create_index(
        "ix_forge_mcp_tools_trust_tier_required",
        "forge_mcp_tools",
        ["trust_tier_required"],
    )
    _enable_rls("forge_mcp_tools")


def downgrade() -> None:
    _disable_rls("forge_mcp_tools")
    op.drop_table("forge_mcp_tools")
    _disable_rls("forge_mcp_servers")
    op.drop_table("forge_mcp_servers")
