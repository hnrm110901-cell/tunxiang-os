"""v013: Add banquet_proposals and banquet_quotations tables

These tables were missing from v004 — the lifecycle service stored
proposals and quotations only in memory dicts.

Revision ID: v013
Revises: v012
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "v013"
down_revision= "v012"
branch_labels= None
depends_on= None

NEW_TABLES = ["banquet_proposals", "banquet_quotations", "banquet_feedbacks", "banquet_cases"]


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ─── banquet_proposals ───
    op.create_table(
        "banquet_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("tiers", JSON, nullable=False, comment="三档方案明细"),
        sa.Column("recommended_tier", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_proposals_lead", "banquet_proposals", ["lead_id"])

    # ─── banquet_quotations ───
    op.create_table(
        "banquet_quotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("menu_items", JSON, nullable=True),
        sa.Column("base_total_fen", sa.BigInteger, nullable=False),
        sa.Column("adjustments", JSON, nullable=True),
        sa.Column("adjustment_total_fen", sa.BigInteger, server_default="0"),
        sa.Column("final_total_fen", sa.BigInteger, nullable=False),
        sa.Column("cost_breakdown", JSON, nullable=True),
        sa.Column("margin_fen", sa.BigInteger, server_default="0"),
        sa.Column("margin_rate", sa.Float, server_default="0"),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_quotations_lead", "banquet_quotations", ["lead_id"])

    # ─── banquet_feedbacks ───
    op.create_table(
        "banquet_feedbacks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("satisfaction_score", sa.Integer, nullable=False),
        sa.Column("satisfaction_level", sa.String(20), nullable=False),
        sa.Column("feedback_text", sa.Text, nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_feedbacks_contract", "banquet_feedbacks", ["contract_id"])

    # ─── banquet_cases ───
    op.create_table(
        "banquet_cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_no", sa.String(64), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("final_total_fen", sa.BigInteger, nullable=False),
        sa.Column("satisfaction_score", sa.Integer, nullable=True),
        sa.Column("feedback_text", sa.Text, nullable=True),
        sa.Column("photos", JSON, nullable=True),
        sa.Column("highlights", JSON, nullable=True),
        sa.Column("menu_items", JSON, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_banquet_cases_contract", "banquet_cases", ["contract_id"])
    op.create_index("ix_banquet_cases_event_type", "banquet_cases", ["event_type"])

    # ─── Add consumer_id to banquet_leads for member linkage ───
    op.add_column("banquet_leads", sa.Column("consumer_id", UUID(as_uuid=True), nullable=True))

    # ─── Add requisition_id and order_id to banquet_contracts ───
    op.add_column("banquet_contracts", sa.Column("requisition_id", sa.String(64), nullable=True))
    op.add_column("banquet_contracts", sa.Column("order_id", UUID(as_uuid=True), nullable=True))
    op.add_column("banquet_contracts", sa.Column("payment_id", UUID(as_uuid=True), nullable=True))

    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.drop_column("banquet_contracts", "payment_id")
    op.drop_column("banquet_contracts", "order_id")
    op.drop_column("banquet_contracts", "requisition_id")
    op.drop_column("banquet_leads", "consumer_id")

    for table in reversed(NEW_TABLES):
        _disable_rls(table)
        op.drop_table(table)
