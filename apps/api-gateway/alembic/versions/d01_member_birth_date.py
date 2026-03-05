"""
d01: private_domain_members 新增 birth_date 列（可选，供生日提醒）

Revision ID: d01_member_birth_date
Revises: c01_member_lifecycle
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa

revision = 'd01_member_birth_date'
down_revision = 'c01_member_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'private_domain_members',
        sa.Column('birth_date', sa.Date(), nullable=True, comment='生日（年月日）'),
    )
    op.create_index(
        'ix_pdm_birth_md',
        'private_domain_members',
        [
            sa.text("EXTRACT(MONTH FROM birth_date)"),
            sa.text("EXTRACT(DAY FROM birth_date)"),
        ],
        postgresql_where=sa.text("birth_date IS NOT NULL"),
    )


def downgrade():
    op.drop_index('ix_pdm_birth_md', table_name='private_domain_members')
    op.drop_column('private_domain_members', 'birth_date')
