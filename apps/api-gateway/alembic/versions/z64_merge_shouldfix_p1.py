"""merge Should-Fix P1 heads (D6 LLM + D8/D10 procurement/attendance + D11 exam)

三个并行开发 Agent 产生三个同层 z63 head，此迁移合并为单一 head，
不新增任何 schema 变更。

Revision ID: z64_merge_shouldfix_p1
Revises: z63_d6_llm_governance, z63_d8_d10_procurement_attendance, z63_d11_exam_system
Create Date: 2026-04-17
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "z64_merge_shouldfix_p1"
down_revision = (
    "z63_d6_llm_governance",
    "z63_d8_d10_procurement_attendance",
    "z63_d11_exam_system",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass


def downgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass
