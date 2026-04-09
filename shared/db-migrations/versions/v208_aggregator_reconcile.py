"""v208 — 外卖对账结果 + 差异单表（Y-A5 对账补偿）

配合 v207 aggregator_orders，实现对账持久化。

Revision ID: v208
Revises: v207
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v208"
down_revision = "v207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── aggregator_reconcile_results（对账结果）──
    op.create_table(
        "aggregator_reconcile_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("reconcile_date", sa.Date, nullable=False),
        sa.Column("store_id", sa.String(50), nullable=True),
        sa.Column("local_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("platform_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discrepancy_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("local_total_fen", sa.BigInteger, server_default="0"),
        sa.Column("platform_total_fen", sa.BigInteger, server_default="0"),
        sa.Column("diff_fen", sa.BigInteger, server_default="0"),
        sa.Column("status", sa.String(20), server_default="'completed'"),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("tenant_id", "platform", "reconcile_date", "store_id", name="uq_reconcile_result"),
    )
    op.execute("ALTER TABLE aggregator_reconcile_results ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE aggregator_reconcile_results FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY arr_tenant ON aggregator_reconcile_results
        USING (current_setting('app.current_tenant', TRUE) IS NOT NULL
               AND tenant_id = current_setting('app.current_tenant', TRUE));
    """)

    # ── aggregator_discrepancies（差异单）──
    op.create_table(
        "aggregator_discrepancies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reconcile_result_id", UUID(as_uuid=True),
                  sa.ForeignKey("aggregator_reconcile_results.id"), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_order_id", sa.String(100), nullable=False),
        sa.Column("discrepancy_type", sa.String(30), nullable=False,
                  comment="amount_mismatch/local_only/platform_only/status_mismatch"),
        sa.Column("local_amount_fen", sa.BigInteger, nullable=True),
        sa.Column("platform_amount_fen", sa.BigInteger, nullable=True),
        sa.Column("diff_fen", sa.BigInteger, server_default="0"),
        sa.Column("status", sa.String(20), server_default="'pending'",
                  comment="pending/resolved/ignored"),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.execute("ALTER TABLE aggregator_discrepancies ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE aggregator_discrepancies FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY ad_tenant ON aggregator_discrepancies
        USING (current_setting('app.current_tenant', TRUE) IS NOT NULL
               AND tenant_id = current_setting('app.current_tenant', TRUE));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ad_tenant ON aggregator_discrepancies;")
    op.drop_table("aggregator_discrepancies")
    op.execute("DROP POLICY IF EXISTS arr_tenant ON aggregator_reconcile_results;")
    op.drop_table("aggregator_reconcile_results")
