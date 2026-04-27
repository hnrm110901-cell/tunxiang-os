"""v364: forge_workflows + forge_workflow_runs for Forge v3.0.

Agent编排工作流 + 工作流执行记录。

Revision ID: v364_forge_workflows
Revises: v363_forge_alliance
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v364_forge_workflows"
down_revision: Union[str, None] = "v363_forge_alliance"
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
    # --- forge_workflows ---
    op.create_table(
        "forge_workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.String(50), nullable=False, unique=True),
        sa.Column("workflow_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("creator_id", sa.String(100), nullable=False),
        sa.Column("steps", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("trigger", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("estimated_value_fen", sa.Integer, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("install_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("avg_execution_ms", sa.Integer, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "status IN ('draft','active','paused','archived')",
            name="ck_forge_workflows_status",
        ),
    )
    op.create_index(
        "ix_forge_workflows_status_installs",
        "forge_workflows",
        ["status", sa.text("install_count DESC")],
    )
    op.create_index(
        "ix_forge_workflows_creator",
        "forge_workflows",
        ["creator_id"],
    )
    _enable_rls("forge_workflows")

    # --- forge_workflow_runs ---
    op.create_table(
        "forge_workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.String(50), nullable=False),
        sa.Column("store_id", sa.String(64)),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("trigger_data", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), server_default="running"),
        sa.Column("steps_completed", sa.Integer, server_default=sa.text("0")),
        sa.Column("steps_total", sa.Integer, server_default=sa.text("0")),
        sa.Column("result", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("total_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_cost_fen", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "trigger_type IN ('event','schedule','manual')",
            name="ck_forge_workflow_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled')",
            name="ck_forge_workflow_runs_status",
        ),
    )
    op.create_index(
        "ix_forge_workflow_runs_wf_started",
        "forge_workflow_runs",
        ["workflow_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_forge_workflow_runs_status",
        "forge_workflow_runs",
        ["status"],
    )
    _enable_rls("forge_workflow_runs")


def downgrade() -> None:
    _disable_rls("forge_workflow_runs")
    op.drop_table("forge_workflow_runs")
    _disable_rls("forge_workflows")
    op.drop_table("forge_workflows")
