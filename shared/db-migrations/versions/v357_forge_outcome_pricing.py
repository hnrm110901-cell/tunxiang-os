"""v357: forge_outcome_definitions + forge_outcome_events tables for Forge v2.0 Agent Exchange.

结果定义与结果事件——支持按结果计价的 Agent 交易模型。

Revision ID: v357_forge_outcome_pricing
Revises: v356_forge_ontology_manifests
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v357_forge_outcome_pricing"
down_revision: Union[str, None] = "v356_forge_ontology_manifests"
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


def _enable_rls_append_only(table_name: str) -> None:
    """Append-only RLS: SELECT + INSERT only, no UPDATE/DELETE."""
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
    # --- forge_outcome_definitions ---
    op.create_table(
        "forge_outcome_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("outcome_type", sa.String(30), nullable=False),
        sa.Column("outcome_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("measurement_method", sa.String(20), nullable=False),
        sa.Column("price_fen_per_outcome", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("attribution_window_hours", sa.Integer, nullable=False, server_default=sa.text("24")),
        sa.Column("verification_method", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "outcome_type IN ('conversion','retention','revenue_lift','cost_saved',"
            "'complaint_resolved','recommendation_accepted','churn_prevented','upsell_success')",
            name="ck_forge_outcome_definitions_outcome_type",
        ),
        sa.CheckConstraint(
            "measurement_method IN ('event_count','delta_compare','attribution')",
            name="ck_forge_outcome_definitions_measurement_method",
        ),
        sa.CheckConstraint(
            "verification_method IN ('auto','manual','hybrid')",
            name="ck_forge_outcome_definitions_verification_method",
        ),
    )
    op.create_index(
        "ix_forge_outcome_definitions_app_active",
        "forge_outcome_definitions",
        ["app_id", "is_active"],
    )
    op.create_index(
        "ix_forge_outcome_definitions_type",
        "forge_outcome_definitions",
        ["outcome_type"],
    )
    _enable_rls("forge_outcome_definitions")

    # --- forge_outcome_events (append-only) ---
    op.create_table(
        "forge_outcome_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_id", sa.String(50), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("store_id", sa.String(64)),
        sa.Column("agent_id", sa.String(100)),
        sa.Column("decision_log_id", UUID(as_uuid=True)),
        sa.Column("outcome_data", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("verified", sa.Boolean, server_default=sa.text("false")),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("verified_by", sa.String(100)),
        sa.Column("revenue_fen", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("attributed_agents", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_outcome_events_app_created",
        "forge_outcome_events",
        ["app_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_forge_outcome_events_outcome_verified",
        "forge_outcome_events",
        ["outcome_id", "verified"],
    )
    op.create_index(
        "ix_forge_outcome_events_agent_created",
        "forge_outcome_events",
        ["agent_id", sa.text("created_at DESC")],
    )
    _enable_rls_append_only("forge_outcome_events")


def downgrade() -> None:
    _disable_rls("forge_outcome_events")
    op.drop_table("forge_outcome_events")
    _disable_rls("forge_outcome_definitions")
    op.drop_table("forge_outcome_definitions")
