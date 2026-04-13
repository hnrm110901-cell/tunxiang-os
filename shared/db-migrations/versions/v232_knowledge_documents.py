"""v232 — 知识库文档表（knowledge_documents）

存储知识库文档元数据：标题、来源类型、处理状态、文件哈希（去重）等。
支持 manual/pdf/docx/xlsx/api 五种来源类型，draft→processing→reviewing→published 生命周期。
RLS 使用 NULLIF 安全模式防止空串绕过（审计修复规范）。

Revision ID: v232
Revises: v231
Create Date: 2026-04-12
"""

from alembic import op

revision = "v232b"
down_revision = "v232"
branch_labels = None
depends_on = None

_SAFE_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge_documents (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            title           VARCHAR(512) NOT NULL,
            source_type     VARCHAR(50) NOT NULL DEFAULT 'manual',
            file_path       TEXT,
            file_hash       VARCHAR(64),
            chunk_count     INT NOT NULL DEFAULT 0,
            status          VARCHAR(20) NOT NULL DEFAULT 'draft',
            collection      VARCHAR(100) NOT NULL DEFAULT 'ops_procedures',
            metadata        JSONB NOT NULL DEFAULT '{}',
            error_message   TEXT,
            created_by      VARCHAR(100),
            reviewed_by     VARCHAR(100),
            published_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── 索引 ──────────────────────────────────────────────────────────────
    op.execute("CREATE INDEX ix_kd_tenant ON knowledge_documents (tenant_id);")
    op.execute("CREATE INDEX ix_kd_tenant_status ON knowledge_documents (tenant_id, status);")
    op.execute("CREATE INDEX ix_kd_tenant_collection ON knowledge_documents (tenant_id, collection);")

    # ── RLS ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE knowledge_documents FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY knowledge_documents_tenant_isolation ON knowledge_documents
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING ({_SAFE_COND})
            WITH CHECK ({_SAFE_COND});
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS knowledge_documents_tenant_isolation ON knowledge_documents;")
    op.execute("DROP TABLE IF EXISTS knowledge_documents;")
