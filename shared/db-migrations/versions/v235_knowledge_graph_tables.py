"""v235 — LightRAG 知识图谱三表（kg_nodes / kg_edges / kg_communities）

Phase 3 知识图谱存储层。支持实体节点、关系边、社区检测结果的持久化，
以及基于 pgvector HNSW 索引的向量近邻检索。

Revision ID: v235
Revises: v234
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v235b"
down_revision = "v235"
branch_labels = None
depends_on = None

_SAFE_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()
    if "kg_nodes" in existing:
        return

    # ── 确保 pgvector 扩展可用 ────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ── kg_nodes ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE kg_nodes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            label           VARCHAR(100) NOT NULL,
            name            VARCHAR(512) NOT NULL,
            properties      JSONB NOT NULL DEFAULT '{}',
            embedding       vector(1536),
            community_id    INT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    op.execute("""
        CREATE INDEX ix_kg_nodes_tenant_label
            ON kg_nodes (tenant_id, label);
    """)
    op.execute("""
        CREATE INDEX ix_kg_nodes_tenant_name
            ON kg_nodes (tenant_id, name);
    """)
    op.execute("""
        CREATE INDEX ix_kg_nodes_properties
            ON kg_nodes USING GIN (properties);
    """)
    op.execute("""
        CREATE INDEX ix_kg_nodes_embedding
            ON kg_nodes USING hnsw (embedding vector_cosine_ops);
    """)

    op.execute("ALTER TABLE kg_nodes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kg_nodes FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY kg_nodes_tenant_isolation ON kg_nodes
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)

    # ── kg_edges ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE kg_edges (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            from_node_id    UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
            to_node_id      UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
            rel_type        VARCHAR(100) NOT NULL,
            properties      JSONB NOT NULL DEFAULT '{}',
            weight          FLOAT DEFAULT 1.0,
            source_chunk_id UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    op.execute("""
        CREATE INDEX ix_kg_edges_from_node
            ON kg_edges (from_node_id);
    """)
    op.execute("""
        CREATE INDEX ix_kg_edges_to_node
            ON kg_edges (to_node_id);
    """)
    op.execute("""
        CREATE INDEX ix_kg_edges_tenant_rel
            ON kg_edges (tenant_id, rel_type);
    """)

    op.execute("ALTER TABLE kg_edges ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kg_edges FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY kg_edges_tenant_isolation ON kg_edges
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)

    # ── kg_communities ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE kg_communities (
            id              SERIAL PRIMARY KEY,
            tenant_id       UUID NOT NULL,
            label           VARCHAR(255),
            summary         TEXT,
            node_count      INT DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    op.execute("""
        CREATE INDEX ix_kg_communities_tenant
            ON kg_communities (tenant_id);
    """)

    op.execute("ALTER TABLE kg_communities ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kg_communities FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY kg_communities_tenant_isolation ON kg_communities
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)


def downgrade() -> None:
    # Drop policies first, then tables in reverse dependency order
    op.execute("DROP POLICY IF EXISTS kg_communities_tenant_isolation ON kg_communities;")
    op.execute("DROP TABLE IF EXISTS kg_communities;")

    op.execute("DROP POLICY IF EXISTS kg_edges_tenant_isolation ON kg_edges;")
    op.execute("DROP TABLE IF EXISTS kg_edges;")

    op.execute("DROP POLICY IF EXISTS kg_nodes_tenant_isolation ON kg_nodes;")
    op.execute("DROP TABLE IF EXISTS kg_nodes;")
