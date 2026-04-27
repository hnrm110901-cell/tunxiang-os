"""v231 — 启用 pgvector 扩展（知识库向量检索基础设施）

知识库升级前置依赖：安装 pgvector 扩展以支持 vector 列类型和 HNSW 索引。
pgvector 提供高性能近似最近邻搜索，用于知识库文档的语义检索。

Revision ID: v231
Revises: v230
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v231b"
down_revision = "v231"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Only create if the OS package is installed (avoids aborting the transaction)
    row = conn.execute(sa.text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")).scalar()
    if row:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector;")
