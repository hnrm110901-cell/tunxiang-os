"""v363: forge_alliance_listings + forge_alliance_transactions for Forge v3.0.

跨品牌共享清单 + 联盟交易记录。

Revision ID: v363_forge_alliance
Revises: v362_forge_auto_review
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v363_forge_alliance"
down_revision: Union[str, None] = "v362_forge_auto_review"
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


def _enable_rls_readonly(table_name: str) -> None:
    """Append-only table: only SELECT + INSERT policies."""
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
    # --- forge_alliance_listings ---
    op.create_table(
        "forge_alliance_listings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("owner_tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sharing_mode", sa.String(20), server_default="invited"),
        sa.Column("shared_tenants", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("revenue_share_rate", sa.Numeric(5, 4), server_default=sa.text("0.7000")),
        sa.Column("platform_fee_rate", sa.Numeric(5, 4), server_default=sa.text("0.3000")),
        sa.Column("install_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_revenue_fen", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "sharing_mode IN ('public','invited','private')",
            name="ck_forge_alliance_listings_sharing_mode",
        ),
    )
    op.create_index(
        "ix_forge_alliance_listings_owner_active",
        "forge_alliance_listings",
        ["owner_tenant_id", "is_active"],
    )
    op.create_index(
        "ix_forge_alliance_listings_app",
        "forge_alliance_listings",
        ["app_id"],
    )
    op.create_index(
        "ix_forge_alliance_listings_sharing",
        "forge_alliance_listings",
        ["sharing_mode"],
    )
    _enable_rls("forge_alliance_listings")

    # --- forge_alliance_transactions (append-only: SELECT + INSERT) ---
    op.create_table(
        "forge_alliance_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", sa.String(50), nullable=False),
        sa.Column("consumer_tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount_fen", sa.BigInteger, nullable=False),
        sa.Column("owner_share_fen", sa.BigInteger, nullable=False),
        sa.Column("platform_share_fen", sa.BigInteger, nullable=False),
        sa.Column("transaction_type", sa.String(20), server_default="subscription"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "transaction_type IN ('subscription','outcome','token_usage')",
            name="ck_forge_alliance_transactions_type",
        ),
    )
    op.create_index(
        "ix_forge_alliance_tx_listing_created",
        "forge_alliance_transactions",
        ["listing_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_forge_alliance_tx_consumer_created",
        "forge_alliance_transactions",
        ["consumer_tenant_id", sa.text("created_at DESC")],
    )
    _enable_rls_readonly("forge_alliance_transactions")


def downgrade() -> None:
    _disable_rls("forge_alliance_transactions")
    op.drop_table("forge_alliance_transactions")
    _disable_rls("forge_alliance_listings")
    op.drop_table("forge_alliance_listings")
