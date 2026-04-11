"""日报与情感分析缓存表

Revision: v222
Tables:
  - daily_briefs     门店日报持久化（store_id/date/content_json/sent_at）
  - sentiment_cache  评价情感分析缓存（store_id/platform/date/scores）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v223"
down_revision = "v222"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── daily_briefs 表 ──
    op.create_table(
        "daily_briefs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.VARCHAR(100), nullable=False, comment="门店ID"),
        sa.Column("brief_date", sa.DATE, nullable=False, comment="日报日期"),
        sa.Column(
            "content_json",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
            comment="日报内容（结构化JSON）",
        ),
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="推送时间（NULL=未推送）",
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
        "ix_daily_briefs_tenant_store_date",
        "daily_briefs",
        ["tenant_id", "store_id", "brief_date"],
        unique=True,
    )
    op.create_index(
        "ix_daily_briefs_tenant_date",
        "daily_briefs",
        ["tenant_id", "brief_date"],
    )

    # ── RLS: daily_briefs ──
    op.execute("ALTER TABLE daily_briefs ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY daily_briefs_tenant_isolation ON daily_briefs"
        " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
    )

    # ── sentiment_cache 表 ──
    op.create_table(
        "sentiment_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.VARCHAR(100), nullable=False, comment="门店ID"),
        sa.Column(
            "platform",
            sa.VARCHAR(50),
            nullable=False,
            comment="评价平台: meituan/dianping/douyin/self",
        ),
        sa.Column("cache_date", sa.DATE, nullable=False, comment="统计日期"),
        sa.Column(
            "scores",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
            comment="情感分析得分（avg_score/positive_rate/negative_rate/keyword_counts）",
        ),
        sa.Column("review_count", sa.INTEGER, server_default="0", comment="评价数量"),
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
        "ix_sentiment_cache_tenant_store_platform_date",
        "sentiment_cache",
        ["tenant_id", "store_id", "platform", "cache_date"],
        unique=True,
    )
    op.create_index(
        "ix_sentiment_cache_tenant_date",
        "sentiment_cache",
        ["tenant_id", "cache_date"],
    )

    # ── RLS: sentiment_cache ──
    op.execute("ALTER TABLE sentiment_cache ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY sentiment_cache_tenant_isolation ON sentiment_cache"
        " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS sentiment_cache_tenant_isolation ON sentiment_cache;")
    op.drop_table("sentiment_cache")
    op.execute("DROP POLICY IF EXISTS daily_briefs_tenant_isolation ON daily_briefs;")
    op.drop_table("daily_briefs")
