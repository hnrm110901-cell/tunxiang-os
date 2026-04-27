"""v360: forge_evidence_cards table for Forge v2.0 Agent Exchange.

证据卡片——安全扫描、性能基准、合规认证、护栏测试等可验证的信任凭证。

Revision ID: v360_forge_evidence_cards
Revises: v359_forge_smart_discovery
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v360_forge_evidence_cards"
down_revision: Union[str, None] = "v359_forge_smart_discovery"
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
    # --- forge_evidence_cards ---
    op.create_table(
        "forge_evidence_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("card_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("evidence_data", sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("score", sa.Integer),
        sa.Column("verified_by", sa.String(100), server_default=""),
        sa.Column("verification_method", sa.String(20), server_default="auto"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.CheckConstraint(
            "card_type IN ('security_scan','performance_benchmark','compliance_cert',"
            "'guardrail_test','customer_case','data_privacy','uptime_sla')",
            name="ck_forge_evidence_cards_card_type",
        ),
        sa.CheckConstraint(
            "verification_method IN ('auto','manual','third_party')",
            name="ck_forge_evidence_cards_verification_method",
        ),
    )
    op.create_index(
        "ix_forge_evidence_cards_app_type_active",
        "forge_evidence_cards",
        ["app_id", "card_type", "is_active"],
    )
    op.create_index(
        "ix_forge_evidence_cards_type_score",
        "forge_evidence_cards",
        ["card_type", sa.text("score DESC")],
    )
    _enable_rls("forge_evidence_cards")


def downgrade() -> None:
    _disable_rls("forge_evidence_cards")
    op.drop_table("forge_evidence_cards")
