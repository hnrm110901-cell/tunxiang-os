"""z63 — D6 AI 决策层 Should-Fix P1 (LLM 治理 + Agent 记忆持久化)

两张新表：
  Task 2: prompt_audit_logs  — LLM 调用全量审计（input hash / risk / output flags / cost）
  Task 3: agent_memories     — Agent 三级记忆持久层（warm/cold）

模型来源（只读）:
  src/models/prompt_audit_log.py
  src/models/agent_memory.py

Revision ID: z63_d6_llm_governance
Revises: z62_merge_mustfix_p0
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z63_d6_llm_governance"
down_revision = "z62_merge_mustfix_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── prompt_audit_logs ────────────────────────────────────────────────
    op.create_table(
        "prompt_audit_logs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_prompt_audit_logs_request_id", "prompt_audit_logs", ["request_id"])
    op.create_index("ix_prompt_audit_logs_user_id", "prompt_audit_logs", ["user_id"])
    op.create_index("idx_prompt_audit_created", "prompt_audit_logs", ["created_at"])
    op.create_index(
        "idx_prompt_audit_user_created",
        "prompt_audit_logs",
        ["user_id", "created_at"],
    )

    # ─── agent_memories ───────────────────────────────────────────────────
    op.create_table(
        "agent_memories",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("level", sa.String(16), nullable=False, server_default="warm"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("agent_id", "session_id", "key", name="uq_agent_memory_key"),
    )
    op.create_index("ix_agent_memories_agent_id", "agent_memories", ["agent_id"])
    op.create_index("ix_agent_memories_session_id", "agent_memories", ["session_id"])
    op.create_index("idx_agent_memory_expires", "agent_memories", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_agent_memory_expires", table_name="agent_memories")
    op.drop_index("ix_agent_memories_session_id", table_name="agent_memories")
    op.drop_index("ix_agent_memories_agent_id", table_name="agent_memories")
    op.drop_table("agent_memories")

    op.drop_index("idx_prompt_audit_user_created", table_name="prompt_audit_logs")
    op.drop_index("idx_prompt_audit_created", table_name="prompt_audit_logs")
    op.drop_index("ix_prompt_audit_logs_user_id", table_name="prompt_audit_logs")
    op.drop_index("ix_prompt_audit_logs_request_id", table_name="prompt_audit_logs")
    op.drop_table("prompt_audit_logs")
