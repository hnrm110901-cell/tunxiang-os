"""Agent Memory 持久化表 — 跨会话记忆存储

支持 Agent 在多次会话之间保留洞察、规则、偏好等记忆，
并提供过期淘汰、访问计数、相似度搜索等能力。

Revision ID: v233
Revises: v232
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v233"
down_revision = "v232c"
branch_labels = None
depends_on = None

# RLS 标准条件
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _add_rls(table: str, prefix: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {prefix}_tenant ON {table}
        USING ({_RLS_COND})
        WITH CHECK ({_RLS_COND})
    """)


def upgrade() -> None:
    # ── 1. 创建 agent_memories 表 ──
    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("memory_type", sa.String(50), nullable=False),
        sa.Column("memory_key", sa.String(200), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("store_id", postgresql.UUID(), nullable=True),
        sa.Column("session_id", postgresql.UUID(), nullable=True),
        sa.Column("embedding_id", sa.String(200), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_accessed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )

    # ── 2. 创建索引 ──
    op.create_index(
        "idx_agent_memories_tenant_agent",
        "agent_memories",
        ["tenant_id", "agent_id"],
    )
    op.create_index(
        "idx_agent_memories_type_key",
        "agent_memories",
        ["tenant_id", "memory_type", "memory_key"],
    )
    op.create_index(
        "idx_agent_memories_store",
        "agent_memories",
        ["tenant_id", "store_id"],
        postgresql_where=sa.text("store_id IS NOT NULL"),
    )

    # ── 3. RLS ──
    _add_rls("agent_memories", "agent_mem")


def downgrade() -> None:
    op.drop_table("agent_memories")
