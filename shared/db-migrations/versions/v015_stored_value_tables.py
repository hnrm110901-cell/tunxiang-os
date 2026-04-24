"""v015: Create stored value card tables (储值卡/预付费)

New tables:
  - stored_value_cards     储值卡主表
  - stored_value_transactions  储值卡交易流水
  - recharge_rules         充值赠送规则

RLS: v006+ safe pattern with NULL guard + FORCE

Revision ID: v015
Revises: v014
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "v015"
down_revision = "v014"
branch_labels = None
depends_on = None

NEW_TABLES = ["stored_value_cards", "stored_value_transactions", "recharge_rules"]

_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_safe_rls(table_name: str) -> None:
    """v006+ safe RLS: 4 policies + NULL guard + FORCE"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_SAFE_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_SAFE_CONDITION})"),
    ]:
        op.execute(f"CREATE POLICY {table_name}_rls_{action} ON {table_name} {clause}")


def upgrade() -> None:
    # ── stored_value_cards ──
    op.create_table(
        "stored_value_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column("card_no", sa.String(32), unique=True, nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("card_type", sa.String(20), nullable=False, server_default="personal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("balance_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("gift_balance_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_recharged_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_consumed_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_refunded_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("store_id", UUID(as_uuid=True)),
        sa.Column("operator_id", UUID(as_uuid=True)),
        sa.Column("extra", JSON),
        comment="储值卡",
    )
    op.create_index("idx_sv_card_customer", "stored_value_cards", ["customer_id", "status"])

    # ── stored_value_transactions ──
    op.create_table(
        "stored_value_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column("card_id", UUID(as_uuid=True), sa.ForeignKey("stored_value_cards.id"), nullable=False, index=True),
        sa.Column("txn_type", sa.String(20), nullable=False),
        sa.Column("amount_fen", sa.Integer, nullable=False),
        sa.Column("gift_amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("balance_after_fen", sa.Integer, nullable=False),
        sa.Column("gift_balance_after_fen", sa.Integer, nullable=False),
        sa.Column("order_id", UUID(as_uuid=True)),
        sa.Column("operator_id", UUID(as_uuid=True)),
        sa.Column("store_id", UUID(as_uuid=True)),
        sa.Column("remark", sa.String(255)),
        sa.Column("extra", JSON),
        comment="储值卡交易流水",
    )
    op.create_index("idx_sv_txn_card_time", "stored_value_transactions", ["card_id", "created_at"])

    # ── recharge_rules ──
    op.create_table(
        "recharge_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column("rule_name", sa.String(100), nullable=False),
        sa.Column("recharge_amount_fen", sa.Integer, nullable=False),
        sa.Column("gift_amount_fen", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("start_date", sa.DateTime(timezone=True)),
        sa.Column("end_date", sa.DateTime(timezone=True)),
        sa.Column("store_ids", JSON),
        comment="充值赠送规则",
    )

    for table in NEW_TABLES:
        _enable_safe_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.drop_table(table)
