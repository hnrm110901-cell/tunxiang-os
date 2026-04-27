"""v365: forge_ecosystem_metrics for Forge v3.0.

生态健康指标时序表——ISV活跃率、产品质量评分、安装密度、结果转化率等。

Revision ID: v365_forge_ecosystem_metrics
Revises: v364_forge_workflows
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v365_forge_ecosystem_metrics"
down_revision: Union[str, None] = "v364_forge_workflows"
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
    # --- forge_ecosystem_metrics ---
    op.create_table(
        "forge_ecosystem_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date, nullable=False),
        sa.Column("isv_active_rate", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("product_quality_score", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("install_density", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("outcome_conversion_rate", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("token_efficiency", sa.Numeric(10, 2), server_default=sa.text("0")),
        sa.Column("developer_nps", sa.Integer, server_default=sa.text("0")),
        sa.Column("tthw_minutes", sa.Integer, server_default=sa.text("0")),
        sa.Column("ecosystem_gmv_fen", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("composite_score", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("details", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("tenant_id", "metric_date", name="uq_forge_ecosystem_metrics_tenant_date"),
    )
    op.create_index(
        "ix_forge_ecosystem_metrics_date",
        "forge_ecosystem_metrics",
        [sa.text("metric_date DESC")],
    )
    _enable_rls("forge_ecosystem_metrics")


def downgrade() -> None:
    _disable_rls("forge_ecosystem_metrics")
    op.drop_table("forge_ecosystem_metrics")
