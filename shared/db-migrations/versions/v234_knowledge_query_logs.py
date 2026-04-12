"""v234 — 知识库查询日志表（knowledge_query_logs）

记录每次知识库检索的查询文本、复杂度、召回数量、相关性评分、延迟等指标，
用于检索质量监控和 RAG 管线调优。

Revision ID: v234
Revises: v233
Create Date: 2026-04-12
"""

from alembic import op

revision = "v234"
down_revision = "v233"
branch_labels = None
depends_on = None

_SAFE_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge_query_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            query           TEXT NOT NULL,
            collection      VARCHAR(100),
            query_complexity VARCHAR(20),
            retrieved_count INT DEFAULT 0,
            reranked_count  INT DEFAULT 0,
            relevance_max   FLOAT,
            latency_ms      INT,
            rewrite_count   INT DEFAULT 0,
            answer_source   VARCHAR(50),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── 索引 ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX ix_kql_tenant_created
            ON knowledge_query_logs (tenant_id, created_at DESC);
    """)

    # ── RLS ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE knowledge_query_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE knowledge_query_logs FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY knowledge_query_logs_tenant_isolation ON knowledge_query_logs
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS knowledge_query_logs_tenant_isolation ON knowledge_query_logs;")
    op.execute("DROP TABLE IF EXISTS knowledge_query_logs;")
