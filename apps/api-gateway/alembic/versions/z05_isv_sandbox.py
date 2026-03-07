"""add is_sandbox to isv_api_keys

Revision ID: z05_isv_sandbox
Revises: z04_isv_platform
Create Date: 2026-03-07 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'z05_isv_sandbox'
down_revision = 'z04_isv_platform'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'isv_api_keys',
        sa.Column('is_sandbox', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('isv_api_keys', 'is_sandbox')
