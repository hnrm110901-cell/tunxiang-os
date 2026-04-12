"""Multi-Agent 协调协议 — agent_messages 消息总线表

为 Agent 间通信提供持久化消息队列，支持 request/response/notification/delegation
四种消息类型，以及会话线程和优先级排序。

Revision ID: v234
Revises: v233
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v234"
down_revision = "v233"
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
    # ── 1. 创建 agent_messages 表 ──
    op.create_table(
        "agent_messages",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("session_id", postgresql.UUID(), nullable=True),
        sa.Column("from_agent_id", sa.String(100), nullable=False),
        sa.Column("to_agent_id", sa.String(100), nullable=True),
        sa.Column("message_type", sa.String(50), nullable=False),
        sa.Column("action", sa.String(100), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(), nullable=True),
        sa.Column("parent_message_id", postgresql.UUID(), nullable=True),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )

    # ── 2. 创建索引 ──
    op.create_index(
        "idx_agent_messages_to",
        "agent_messages",
        ["tenant_id", "to_agent_id", "status"],
    )
    op.create_index(
        "idx_agent_messages_session",
        "agent_messages",
        ["tenant_id", "session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.create_index(
        "idx_agent_messages_correlation",
        "agent_messages",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    # ── 3. RLS ──
    _add_rls("agent_messages", "agent_msg")


def downgrade() -> None:
    op.drop_table("agent_messages")
