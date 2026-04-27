"""v358: forge_token_meters + forge_token_prices tables for Forge v2.0 Agent Exchange.

Token 计量与定价——支持按 Token 用量计费的 Agent 交易模型。

Revision ID: v358_forge_token_meters
Revises: v357_forge_outcome_pricing
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v358_forge_token_meters"
down_revision: Union[str, None] = "v357_forge_outcome_pricing"
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
    # --- forge_token_meters ---
    op.create_table(
        "forge_token_meters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("period_key", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_fen", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("budget_fen", sa.Integer, server_default=sa.text("0")),
        sa.Column("alert_threshold", sa.Integer, server_default=sa.text("80")),
        sa.Column("alert_sent", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("tenant_id", "app_id", "period_type", "period_key",
                            name="uq_forge_token_meters_tenant_app_period"),
        sa.CheckConstraint(
            "period_type IN ('daily','monthly')",
            name="ck_forge_token_meters_period_type",
        ),
    )
    # Add generated column via raw SQL (SQLAlchemy doesn't support GENERATED ALWAYS AS ... STORED natively)
    op.execute(
        "ALTER TABLE forge_token_meters "
        "ADD COLUMN total_tokens BIGINT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED"
    )
    op.create_index(
        "ix_forge_token_meters_app_period",
        "forge_token_meters",
        ["app_id", "period_type", "period_key"],
    )
    op.create_index(
        "ix_forge_token_meters_tenant_period",
        "forge_token_meters",
        ["tenant_id", "period_key"],
    )
    _enable_rls("forge_token_meters")

    # --- forge_token_prices ---
    op.create_table(
        "forge_token_prices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False, unique=True),
        sa.Column("input_price_per_1k_fen", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("output_price_per_1k_fen", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("markup_rate", sa.Numeric(5, 4), server_default=sa.text("0.0000")),
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_token_prices_app",
        "forge_token_prices",
        ["app_id"],
    )
    _enable_rls("forge_token_prices")


def downgrade() -> None:
    _disable_rls("forge_token_prices")
    op.drop_table("forge_token_prices")
    _disable_rls("forge_token_meters")
    op.drop_table("forge_token_meters")
