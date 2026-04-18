"""merge Wave 4 heads (D9 talent + D12 salary item library)

两个 Agent 并行产生 2 个 z66 head，此迁移合并为单一 head，
不新增任何 schema 变更。

Revision ID: z67_merge_wave4
Revises: z66_d9_cost_center_talent_1on1, z66_d12_salary_item_library
Create Date: 2026-04-18
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "z67_merge_wave4"
down_revision = (
    "z66_d9_cost_center_talent_1on1",
    "z66_d12_salary_item_library",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass


def downgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass
