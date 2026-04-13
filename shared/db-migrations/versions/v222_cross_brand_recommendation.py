"""跨品牌会员智能 + 实时推荐引擎

Revision: v222
Tables:
  - recommendation_logs         推荐日志（场景/推荐内容/是否采纳）
  - cross_brand_member_links    跨品牌会员关联（golden_id/brand_id/brand_member_id）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v222"
down_revision = "v221"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── recommendation_logs 推荐日志表 ──

    if 'recommendation_logs' not in existing:
        op.create_table(
            "recommendation_logs",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "customer_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="顾客ID（匿名推荐时可为NULL）",
            ),
            sa.Column(
                "store_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="门店ID",
            ),
            sa.Column(
                "order_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="关联订单ID（加单推荐场景）",
            ),
            sa.Column(
                "scene",
                sa.VARCHAR(50),
                nullable=False,
                comment="推荐场景: order_time/upsell/return_visit",
            ),
            sa.Column(
                "recommended_dish_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="推荐菜品ID",
            ),
            sa.Column(
                "recommended_dish_name",
                sa.VARCHAR(200),
                server_default="",
                comment="推荐菜品名称（冗余，避免JOIN）",
            ),
            sa.Column(
                "score",
                sa.FLOAT,
                server_default="0",
                comment="推荐分数 0-1",
            ),
            sa.Column(
                "reason",
                sa.TEXT,
                server_default="",
                comment="推荐理由文案",
            ),
            sa.Column(
                "reason_type",
                sa.VARCHAR(50),
                server_default="",
                comment="推荐原因类型: history/hot/association/margin/explore/repurchase/premium",
            ),
            sa.Column(
                "is_accepted",
                sa.BOOLEAN,
                server_default="FALSE",
                nullable=False,
                comment="顾客是否采纳推荐",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="FALSE", nullable=False),
        )
        op.create_index(
            "ix_recommendation_logs_tenant_scene",
            "recommendation_logs",
            ["tenant_id", "scene", "created_at"],
        )
        op.create_index(
            "ix_recommendation_logs_customer",
            "recommendation_logs",
            ["tenant_id", "customer_id", "created_at"],
        )
        op.create_index(
            "ix_recommendation_logs_order",
            "recommendation_logs",
            ["order_id"],
            postgresql_where=sa.text("order_id IS NOT NULL"),
        )

        # RLS: recommendation_logs
        op.execute(
            "ALTER TABLE recommendation_logs ENABLE ROW LEVEL SECURITY;"
        )
        op.execute(
            "CREATE POLICY recommendation_logs_tenant_isolation ON recommendation_logs"
            " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
        )

        # ── cross_brand_member_links 跨品牌会员关联表 ──

    if 'cross_brand_member_links' not in existing:
        op.create_table(
            "cross_brand_member_links",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "golden_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                comment="跨品牌统一 Golden ID",
            ),
            sa.Column(
                "brand_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                comment="品牌ID",
            ),
            sa.Column(
                "brand_member_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                comment="品牌内会员ID（customer_id）",
            ),
            sa.Column(
                "phone_hash",
                sa.VARCHAR(128),
                nullable=True,
                comment="手机号哈希（用于匹配）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="FALSE", nullable=False),
        )
        op.create_index(
            "ix_cross_brand_links_golden_id",
            "cross_brand_member_links",
            ["tenant_id", "golden_id"],
        )
        op.create_index(
            "ix_cross_brand_links_brand_member",
            "cross_brand_member_links",
            ["tenant_id", "brand_id", "brand_member_id"],
        )
        op.create_index(
            "ix_cross_brand_links_phone_hash",
            "cross_brand_member_links",
            ["tenant_id", "phone_hash"],
            postgresql_where=sa.text("phone_hash IS NOT NULL"),
        )
        # 唯一约束：同一租户+品牌+会员只能有一条有效链接
        op.create_unique_constraint(
            "uq_cross_brand_links_tenant_brand_member",
            "cross_brand_member_links",
            ["tenant_id", "brand_id", "brand_member_id"],
        )

        # RLS: cross_brand_member_links
        op.execute(
            "ALTER TABLE cross_brand_member_links ENABLE ROW LEVEL SECURITY;"
        )
        op.execute(
            "CREATE POLICY cross_brand_member_links_tenant_isolation ON cross_brand_member_links"
            " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
        )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS cross_brand_member_links_tenant_isolation"
        " ON cross_brand_member_links;"
    )
    op.drop_table("cross_brand_member_links")

    op.execute(
        "DROP POLICY IF EXISTS recommendation_logs_tenant_isolation"
        " ON recommendation_logs;"
    )
    op.drop_table("recommendation_logs")
