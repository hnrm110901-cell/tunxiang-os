"""merge D7/D9+D11/D12 Must-Fix P0 heads

三个并行开发 Agent 产生三个同层 z61 head，此迁移合并为单一 head，
不新增任何 schema 变更。

Revision ID: z62_merge_mustfix_p0
Revises: z61_d7_finance_must_fix, z61_compliance_training, z61_d12_payroll_compliance
Create Date: 2026-04-17
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "z62_merge_mustfix_p0"
down_revision = (
    "z61_d7_finance_must_fix",
    "z61_compliance_training",
    "z61_d12_payroll_compliance",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass


def downgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass
