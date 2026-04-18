"""merge Wave 6 heads (D14 marketplace + D15 i18n multi-country)

两个并行开发 Agent 产生两个同层 z70 head，此迁移合并为单一 head，
不新增任何 schema 变更。两侧都不改对方表，无冲突。

Revision ID: z71_merge_wave6
Revises: z70_d14_marketplace, z70_d15_i18n_multi_country
Create Date: 2026-04-18
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "z71_merge_wave6"
down_revision = (
    "z70_d14_marketplace",
    "z70_d15_i18n_multi_country",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass


def downgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass
