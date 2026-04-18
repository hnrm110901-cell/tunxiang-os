"""merge Wave 5 heads (D9 e-sig + D11 OKR/Learning/Pulse + D13 HR Assistant)

三个并行开发 Agent 产生三个同层 z68 head，此迁移合并为单一 head，
不新增任何 schema 变更。

Revision ID: z69_merge_wave5
Revises: z68_d9_e_signature_legal_entity, z68_d11_okr_elearning_pulse, z68_d13_hr_assistant
Create Date: 2026-04-18
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "z69_merge_wave5"
down_revision = (
    "z68_d9_e_signature_legal_entity",
    "z68_d11_okr_elearning_pulse",
    "z68_d13_hr_assistant",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass


def downgrade() -> None:
    """空 merge — 无 schema 变更"""
    pass
