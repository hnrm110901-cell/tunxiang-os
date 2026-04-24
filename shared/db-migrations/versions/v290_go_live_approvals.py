"""v237 — GO-TO-LIVE 手动批准记录表

新增：
  go_live_approvals — 三商户上线批准记录（含 RLS）

背景：May Week 4 评审时若某商户评分略低但现场演示通过，
允许人工批准上线，此表持久化批准人/备注/时间供审计留痕。

Revision ID: v237
Revises: v236
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v290"
down_revision = "v236"
branch_labels = None
depends_on = None


def _add_rls(table: str, policy: str, using_expr: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = '{table}' AND policyname = '{policy}'
            ) THEN
                EXECUTE $pol$
                    CREATE POLICY {policy} ON {table}
                    USING ({using_expr})
                $pol$;
            END IF;
        END;
        $$
    """)


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    if "go_live_approvals" not in existing:
        op.create_table(
            "go_live_approvals",
            sa.Column(
                "id",
                sa.UUID,
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", sa.UUID, nullable=False, comment="租户ID（RLS）"),
            sa.Column(
                "merchant_code",
                sa.Text,
                nullable=False,
                unique=True,
                comment="商户代码：czyz / zqx / sgc",
            ),
            sa.Column("approver", sa.Text, nullable=False, comment="批准人姓名"),
            sa.Column("notes", sa.Text, nullable=True, comment="批准备注"),
            sa.Column(
                "approved_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )
        op.create_index(
            "ix_go_live_approvals_merchant",
            "go_live_approvals",
            ["merchant_code"],
        )
        _add_rls(
            "go_live_approvals",
            "gla_tenant",
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS go_live_approvals CASCADE")
