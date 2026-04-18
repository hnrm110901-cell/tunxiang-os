"""z68 — D13 HR 数字人助手（hr_conversations / hr_messages）

新增 2 张表：
  hr_conversations  员工与 HR 助手的对话主体
  hr_messages       每条对话消息（含 tool_calls 审计）

⚠ 与 Agent-L (z68_d9_e_signature_legal_entity)、Agent-M (z68_d11_okr_elearning_pulse)
  并行产生 3 个 z68 head，由主线程后续合并。

Revision ID: z68_d13_hr_assistant
Revises: z67_merge_wave4
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z68_d13_hr_assistant"
down_revision = "z67_merge_wave4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── hr_conversations ─────────────────────────────────────
    op.create_table(
        "hr_conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("feedback_score", sa.Integer(), nullable=True),
        sa.Column("feedback_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hr_conv_emp_active", "hr_conversations", ["employee_id", "last_active_at"])

    # ── hr_messages ──────────────────────────────────────────
    op.create_table(
        "hr_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id", UUID(as_uuid=True),
            sa.ForeignKey("hr_conversations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls_json", JSONB, nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_fen", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hr_messages")
    op.drop_index("ix_hr_conv_emp_active", table_name="hr_conversations")
    op.drop_table("hr_conversations")
