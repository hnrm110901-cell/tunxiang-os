"""v252 — 宴会KDS出品表 + 宴会场次定金表

新增表：
  banquet_kds_dishes         — KDS出品状态追踪（场次维度排菜列表）
  banquet_session_deposits   — 宴席场次定金收取/抵扣/退款记录

两表均含 RLS（NULLIF app.tenant_id）。

Revision ID: v252
Revises: v251
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v252"
down_revision = "v251"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_tables = sa.inspect(conn).get_table_names()

    # ── banquet_kds_dishes ───────────────────────────────────────────────────
    if "banquet_kds_dishes" not in existing_tables:
        op.create_table(
            "banquet_kds_dishes",
            sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.UUID, nullable=False),
            sa.Column("session_id", sa.UUID, nullable=False, comment="关联 banquet_sessions.id"),
            sa.Column("dish_id", sa.Text, nullable=False, comment="菜品ID（来自菜单）"),
            sa.Column("dish_name", sa.Text, nullable=False),
            sa.Column("total_qty", sa.Integer, nullable=False, server_default="1"),
            sa.Column("served_qty", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "serve_status",
                sa.Text,
                nullable=False,
                server_default="pending",
                comment="pending / serving / served",
            ),
            sa.Column("called_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("served_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("sequence_no", sa.Integer, nullable=False, server_default="1", comment="出品顺序"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        )
        op.create_index(
            "ix_bkd_tenant_session",
            "banquet_kds_dishes",
            ["tenant_id", "session_id"],
        )
        op.create_index(
            "ix_bkd_session_seq",
            "banquet_kds_dishes",
            ["session_id", "sequence_no"],
        )
        op.execute("ALTER TABLE banquet_kds_dishes ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE banquet_kds_dishes FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'banquet_kds_dishes' AND policyname = 'bkd_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY bkd_tenant ON banquet_kds_dishes
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)

    # ── banquet_session_deposits ─────────────────────────────────────────────
    if "banquet_session_deposits" not in existing_tables:
        op.create_table(
            "banquet_session_deposits",
            sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.UUID, nullable=False),
            sa.Column("session_id", sa.UUID, nullable=False, comment="关联 banquet_sessions.id"),
            sa.Column("amount_fen", sa.BigInteger, nullable=False, comment="收取金额（分）"),
            sa.Column("balance_fen", sa.BigInteger, nullable=False, comment="当前余额（分）"),
            sa.Column(
                "payment_method",
                sa.Text,
                nullable=False,
                server_default="cash",
                comment="cash / wechat / alipay / bank_transfer",
            ),
            sa.Column(
                "status",
                sa.Text,
                nullable=False,
                server_default="active",
                comment="active / applied / refunded",
            ),
            sa.Column("operator_id", sa.Text, nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("collected_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        )
        op.create_index(
            "ix_bsd_tenant_session",
            "banquet_session_deposits",
            ["tenant_id", "session_id"],
        )
        op.create_index(
            "ix_bsd_session_status",
            "banquet_session_deposits",
            ["session_id", "status"],
        )
        op.execute("ALTER TABLE banquet_session_deposits ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE banquet_session_deposits FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'banquet_session_deposits' AND policyname = 'bsd_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY bsd_tenant ON banquet_session_deposits
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_session_deposits CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_kds_dishes CASCADE")
