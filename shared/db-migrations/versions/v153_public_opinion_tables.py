"""v153 — 舆情监控表

新增两张表：
  public_opinion_mentions — 舆情提及记录（大众点评/美团/微博/微信等平台）
  mv_public_opinion       — 舆情统计物化视图（手动维护，按ISO周聚合）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 模式。
投影器：PublicOpinionProjector（消费 opinion.* 事件）

Revision ID: v153
Revises: v152
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, NUMERIC, UUID

revision = "v153"
down_revision= "v152"
branch_labels= None
depends_on= None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── 1. public_opinion_mentions 舆情提及记录表 ─────────────────────
    if "public_opinion_mentions" not in _existing:
        op.create_table(
            "public_opinion_mentions",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True),
            # 平台来源：dianping/meituan/weibo/wechat
            sa.Column("platform", sa.String(50), nullable=True),
            sa.Column("source_url", sa.Text, nullable=True),
            sa.Column("content", sa.Text, nullable=True),
            # 情感倾向：positive/neutral/negative
            sa.Column("sentiment", sa.String(20), nullable=True),
            # 情感评分 0.00 ~ 1.00
            sa.Column("sentiment_score", NUMERIC(3, 2), nullable=True),
            # 评分 0.0 ~ 5.0
            sa.Column("rating", NUMERIC(2, 1), nullable=True),
            sa.Column("author_name", sa.String(100), nullable=True),
            sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "captured_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
            sa.Column(
                "is_resolved", sa.Boolean, nullable=False, server_default="false",
            ),
            sa.Column("resolution_note", sa.Text, nullable=True),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='public_opinion_mentions' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_public_opinion_mentions_tenant_store ON public_opinion_mentions (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='public_opinion_mentions' AND column_name IN ('tenant_id', 'platform')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_public_opinion_mentions_tenant_platform ON public_opinion_mentions (tenant_id, platform)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='public_opinion_mentions' AND (column_name = 'published_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_public_opinion_mentions_published_at ON public_opinion_mentions (published_at)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='public_opinion_mentions' AND column_name IN ('tenant_id', 'sentiment')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_public_opinion_mentions_sentiment ON public_opinion_mentions (tenant_id, sentiment)';
            END IF;
        END $$;
    """)

    # RLS
    op.execute("ALTER TABLE public_opinion_mentions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE public_opinion_mentions FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY public_opinion_mentions_tenant_isolation
        ON public_opinion_mentions
        AS PERMISSIVE FOR ALL
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 2. mv_public_opinion 舆情统计物化视图（手动维护表） ────────────
    if "mv_public_opinion" not in _existing:
        op.create_table(
            "mv_public_opinion",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True),
            # ISO周一（该周的起始日期）
            sa.Column("stat_week", sa.Date, nullable=False),
            # 平台：dianping/meituan/weibo/wechat
            sa.Column("platform", sa.String(50), nullable=False),
            sa.Column(
                "total_mentions", sa.Integer, nullable=False, server_default="0",
            ),
            sa.Column(
                "positive_count", sa.Integer, nullable=False, server_default="0",
            ),
            sa.Column(
                "neutral_count", sa.Integer, nullable=False, server_default="0",
            ),
            sa.Column(
                "negative_count", sa.Integer, nullable=False, server_default="0",
            ),
            # 平均评分 0.00 ~ 5.00
            sa.Column("avg_rating", NUMERIC(3, 2), nullable=True),
            # 平均情感评分 0.00 ~ 1.00
            sa.Column("avg_sentiment_score", NUMERIC(3, 2), nullable=True),
            # 高频投诉关键词列表：[{"keyword": "xxx", "count": N}, ...]
            sa.Column(
                "top_complaint_keywords", JSONB, nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "updated_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='mv_public_opinion' AND column_name IN ('tenant_id', 'store_id', 'stat_week', 'platform')) = 4 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_public_opinion_week_platform ON mv_public_opinion (tenant_id, store_id, stat_week, platform)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='mv_public_opinion' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_mv_public_opinion_tenant_store ON mv_public_opinion (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='mv_public_opinion' AND column_name IN ('tenant_id', 'stat_week')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_mv_public_opinion_stat_week ON mv_public_opinion (tenant_id, stat_week)';
            END IF;
        END $$;
    """)

    # RLS
    op.execute("ALTER TABLE mv_public_opinion ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE mv_public_opinion FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY mv_public_opinion_tenant_isolation
        ON mv_public_opinion
        AS PERMISSIVE FOR ALL
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS mv_public_opinion_tenant_isolation ON mv_public_opinion;"
    )
    op.drop_table("mv_public_opinion")
    op.execute(
        "DROP POLICY IF EXISTS public_opinion_mentions_tenant_isolation "
        "ON public_opinion_mentions;"
    )
    op.drop_table("public_opinion_mentions")
