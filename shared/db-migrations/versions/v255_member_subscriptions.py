"""v255 — 付费会员订阅表（member_subscriptions）

月卡/季卡/年卡订阅记录，关联微信支付订单号，追踪订阅生命周期。

Revision ID: v255b
Revises: v253
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v255b"
down_revision = "v253b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    if "member_subscriptions" not in existing:
        op.create_table(
            "member_subscriptions",
            sa.Column(
                "id",
                sa.UUID,
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", sa.UUID, nullable=False, comment="租户ID（RLS）"),
            sa.Column("member_id", sa.Text, nullable=True, comment="会员ID（可选）"),
            sa.Column("openid", sa.Text, nullable=True, comment="微信 openid，支付用"),
            sa.Column(
                "plan_id",
                sa.String(20),
                nullable=False,
                comment="订阅方案：monthly / quarterly / yearly",
            ),
            sa.Column("plan_name", sa.String(50), nullable=False, comment="方案名称"),
            sa.Column("price_fen", sa.Integer, nullable=False, comment="支付金额（分）"),
            sa.Column("period_days", sa.Integer, nullable=False, comment="有效天数"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'pending_payment'"),
                comment="状态：pending_payment / active / expired / cancelled",
            ),
            sa.Column(
                "out_trade_no",
                sa.String(64),
                nullable=True,
                unique=True,
                comment="微信商户订单号（唯一）",
            ),
            sa.Column("prepay_id", sa.Text, nullable=True, comment="微信预支付 ID"),
            sa.Column(
                "started_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="订阅开始时间",
            ),
            sa.Column(
                "expires_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="订阅到期时间",
            ),
            sa.Column(
                "auto_renew",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
                comment="是否自动续费",
            ),
            sa.Column(
                "cancelled_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="取消自动续费时间",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
        )

        op.create_index(
            "ix_member_subscriptions_tenant",
            "member_subscriptions",
            ["tenant_id"],
        )
        op.create_index(
            "ix_member_subscriptions_tenant_status",
            "member_subscriptions",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_member_subscriptions_out_trade_no",
            "member_subscriptions",
            ["out_trade_no"],
        )

        op.execute("ALTER TABLE member_subscriptions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE member_subscriptions FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'member_subscriptions'
                      AND policyname = 'ms_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY ms_tenant ON member_subscriptions
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS member_subscriptions CASCADE")
