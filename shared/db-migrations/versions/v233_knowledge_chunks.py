"""v233 — 知识库分块表（knowledge_chunks）

存储文档分块内容及其向量嵌入，支持语义检索（HNSW）和关键词检索（GIN + tsvector）。
embedding 列使用 pgvector 的 vector(1536) 类型，匹配 text-embedding-3-small 维度。
tsvector 触发器自动维护全文搜索索引。

Revision ID: v233
Revises: v232
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v233b"
down_revision = "v233"
branch_labels = None
depends_on = None

_SAFE_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # Ensure vector extension is active (may have been skipped in v231b)
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")).scalar()
    if row:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    existing = sa.inspect(conn).get_table_names()
    if "knowledge_chunks" in existing:
        return

    op.execute("""
        CREATE TABLE knowledge_chunks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            document_id     UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            collection      VARCHAR(100) NOT NULL,
            doc_id          VARCHAR(255) NOT NULL,
            chunk_index     INT NOT NULL DEFAULT 0,
            text            TEXT NOT NULL,
            embedding       vector(1536),
            token_count     INT NOT NULL DEFAULT 0,
            metadata        JSONB NOT NULL DEFAULT '{}',
            tsv             TSVECTOR,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── 索引 ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX ix_kc_embedding
            ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
    """)
    op.execute("""
        CREATE INDEX ix_kc_tsv
            ON knowledge_chunks USING GIN (tsv);
    """)
    op.execute("CREATE INDEX ix_kc_tenant_collection ON knowledge_chunks (tenant_id, collection);")
    op.execute("CREATE INDEX ix_kc_document ON knowledge_chunks (document_id);")
    op.execute("CREATE INDEX ix_kc_tenant_doc_id ON knowledge_chunks (tenant_id, doc_id);")

    # ── tsvector 自动更新触发器 ───────────────────────────────────────────
    op.execute("""
        CREATE TRIGGER trg_kc_tsv_update
            BEFORE INSERT OR UPDATE OF text ON knowledge_chunks
            FOR EACH ROW EXECUTE FUNCTION
                tsvector_update_trigger(tsv, 'pg_catalog.simple', text);
    """)

    # ── RLS ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY knowledge_chunks_tenant_isolation ON knowledge_chunks
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_kc_tsv_update ON knowledge_chunks;")
    op.execute("DROP POLICY IF EXISTS knowledge_chunks_tenant_isolation ON knowledge_chunks;")
    op.execute("DROP TABLE IF EXISTS knowledge_chunks;")
