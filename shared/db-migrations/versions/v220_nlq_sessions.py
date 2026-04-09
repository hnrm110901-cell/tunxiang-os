"""NLQ对话式经营助手 — 会话与消息持久化

Revision: v220
Tables:
  - nlq_sessions   NLQ会话主表（会话ID/租户/用户/创建时间）
  - nlq_messages   NLQ消息明细（会话ID/角色/内容/意图/SQL/结果/操作）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v220"
down_revision = "v219"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── NLQ 会话主表 ──
    op.create_table(
        "nlq_sessions",
        sa.Column("id", sa.VARCHAR(64), primary_key=True, comment="会话ID (UUID字符串)"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.VARCHAR(100), server_default="", comment="操作用户ID"),
        sa.Column("title", sa.VARCHAR(200), server_default="", comment="会话标题（首条问题截取）"),
        sa.Column("message_count", sa.INTEGER, server_default="0", comment="消息数量"),
        sa.Column("last_intent", sa.VARCHAR(100), server_default="", comment="最后一次意图"),
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
        "ix_nlq_sessions_tenant_created",
        "nlq_sessions",
        ["tenant_id", "created_at"],
    )

    # ── RLS: nlq_sessions ──
    op.execute(
        "ALTER TABLE nlq_sessions ENABLE ROW LEVEL SECURITY;"
    )
    op.execute(
        "CREATE POLICY nlq_sessions_tenant_isolation ON nlq_sessions"
        " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
    )

    # ── NLQ 消息明细表 ──
    op.create_table(
        "nlq_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            sa.VARCHAR(64),
            sa.ForeignKey("nlq_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.VARCHAR(20),
            nullable=False,
            comment="user / assistant / system",
        ),
        sa.Column("content", sa.TEXT, nullable=False, comment="消息内容"),
        sa.Column("intent", sa.VARCHAR(100), server_default="", comment="识别到的意图"),
        sa.Column("matched_sql", sa.TEXT, server_default="", comment="命中的SQL模板"),
        sa.Column(
            "query_result",
            postgresql.JSONB,
            server_default="{}",
            comment="查询结果（结构化数据）",
        ),
        sa.Column(
            "actions",
            postgresql.JSONB,
            server_default="[]",
            comment="建议操作列表",
        ),
        sa.Column("source", sa.VARCHAR(50), server_default="", comment="数据来源: sql_template/agent_call/mv/claude"),
        sa.Column("chart_type", sa.VARCHAR(30), server_default="", comment="建议图表类型"),
        sa.Column(
            "latency_ms",
            sa.INTEGER,
            server_default="0",
            comment="响应延迟毫秒数",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="FALSE", nullable=False),
    )
    op.create_index(
        "ix_nlq_messages_session_created",
        "nlq_messages",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_nlq_messages_tenant_created",
        "nlq_messages",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_nlq_messages_intent",
        "nlq_messages",
        ["intent"],
    )

    # ── RLS: nlq_messages ──
    op.execute(
        "ALTER TABLE nlq_messages ENABLE ROW LEVEL SECURITY;"
    )
    op.execute(
        "CREATE POLICY nlq_messages_tenant_isolation ON nlq_messages"
        " USING (tenant_id = current_setting('app.tenant_id')::UUID);"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS nlq_messages_tenant_isolation ON nlq_messages;")
    op.drop_table("nlq_messages")
    op.execute("DROP POLICY IF EXISTS nlq_sessions_tenant_isolation ON nlq_sessions;")
    op.drop_table("nlq_sessions")
