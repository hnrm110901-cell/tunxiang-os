"""z65 — D5 跨店权限边界 + D7 月结/年结 Nice-to-Have

新增 3 张表：
  - user_store_scopes          用户-门店访问范围
  - month_close_logs           月结/年结执行日志
  - trial_balance_snapshots    月末试算平衡表快照

模型来源（只读）:
  src/models/user_store_scope.py, src/models/month_close.py

Revision ID: z65_d5_d7_closing_access
Revises: z64_merge_shouldfix_p1
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z65_d5_d7_closing_access"
down_revision = "z64_merge_shouldfix_p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────── D5: user_store_scopes ──────────
    op.create_table(
        "user_store_scopes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("access_level", sa.String(20), nullable=False, server_default="read"),
        sa.Column("finance_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_user_store_scope", "user_store_scopes", ["user_id", "store_id"], unique=True)
    op.create_index("idx_uss_store", "user_store_scopes", ["store_id"])

    # ────────── D7: month_close_logs ──────────
    op.create_table(
        "month_close_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("year_month", sa.String(6), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reopened_at", sa.DateTime(), nullable=True),
        sa.Column("reopened_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("snapshot_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_close_store_ym", "month_close_logs", ["store_id", "year_month"], unique=True)

    # ────────── D7: trial_balance_snapshots ──────────
    op.create_table(
        "trial_balance_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("year_month", sa.String(6), nullable=False, index=True),
        sa.Column("account_code", sa.String(20), nullable=False, index=True),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("opening_debit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opening_credit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_debit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_credit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closing_debit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closing_credit_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_tb_store_ym_code",
        "trial_balance_snapshots",
        ["store_id", "year_month", "account_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tb_store_ym_code", table_name="trial_balance_snapshots")
    op.drop_table("trial_balance_snapshots")

    op.drop_index("uq_close_store_ym", table_name="month_close_logs")
    op.drop_table("month_close_logs")

    op.drop_index("idx_uss_store", table_name="user_store_scopes")
    op.drop_index("uq_user_store_scope", table_name="user_store_scopes")
    op.drop_table("user_store_scopes")
