"""customers 表添加企微客户联系字段（SCRM）

Revision ID: v022
Revises: v021
Create Date: 2026-03-30

新增字段：
  wecom_external_userid  — 企微客户联系外部联系人 ID（唯一索引）
  wecom_follow_user      — 负责跟进的导购（企微 userid）
  wecom_follow_at        — 加好友时间
  wecom_remark           — 导购备注

RLS Policy：沿用 customers 表已有策略，新字段无需额外策略。
"""

import sqlalchemy as sa
from alembic import op

revision = "v022a"
down_revision = "v021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加企微客户联系字段
    op.add_column(
        "customers",
        sa.Column("wecom_external_userid", sa.String(128), nullable=True, comment="企微客户联系外部联系人ID"),
    )
    op.add_column(
        "customers",
        sa.Column("wecom_follow_user", sa.String(100), nullable=True, comment="负责跟进的导购（企微userid）"),
    )
    op.add_column(
        "customers",
        sa.Column("wecom_follow_at", sa.DateTime(timezone=True), nullable=True, comment="加好友时间"),
    )
    op.add_column(
        "customers",
        sa.Column("wecom_remark", sa.String(500), nullable=True, comment="导购备注"),
    )

    # 唯一索引（同一租户内 external_userid 唯一）
    # 使用 partial index 排除 NULL（PostgreSQL 支持）
    op.execute(
        """
        CREATE UNIQUE INDEX idx_customer_wecom_external_userid
            ON customers (tenant_id, wecom_external_userid)
            WHERE wecom_external_userid IS NOT NULL;
        """
    )

    # 普通索引，用于按 external_userid 快速查询（企微回调场景）
    op.create_index(
        "idx_customer_wecom_external",
        "customers",
        ["wecom_external_userid"],
        postgresql_where=sa.text("wecom_external_userid IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_customer_wecom_external_userid;")
    op.drop_index("idx_customer_wecom_external", table_name="customers")
    op.drop_column("customers", "wecom_remark")
    op.drop_column("customers", "wecom_follow_at")
    op.drop_column("customers", "wecom_follow_user")
    op.drop_column("customers", "wecom_external_userid")
