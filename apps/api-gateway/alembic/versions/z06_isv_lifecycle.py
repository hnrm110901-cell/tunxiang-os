"""add ISV lifecycle columns

Revision ID: z06_isv_lifecycle
Revises: z05_isv_sandbox
Create Date: 2026-03-07 12:00:00.000000

ISV 认证体系：
- status: active / suspended / pending_verification
- webhook_url: ISV 配置的回调地址
- verified_at: 邮箱验证时间
- upgrade_request_tier: 申请升级的目标套餐
- upgrade_request_reason: 升级理由
- upgrade_requested_at: 升级申请时间
- upgrade_reviewed_at: 审核时间
- upgrade_review_note: 审核意见
"""
from alembic import op
import sqlalchemy as sa

revision = 'z06_isv_lifecycle'
down_revision = 'z05_isv_sandbox'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('isv_developers', sa.Column('status', sa.String(30), nullable=False, server_default='active'))
    op.add_column('isv_developers', sa.Column('webhook_url', sa.String(500)))
    op.add_column('isv_developers', sa.Column('verified_at', sa.DateTime()))
    op.add_column('isv_developers', sa.Column('upgrade_request_tier', sa.String(20)))
    op.add_column('isv_developers', sa.Column('upgrade_request_reason', sa.Text()))
    op.add_column('isv_developers', sa.Column('upgrade_requested_at', sa.DateTime()))
    op.add_column('isv_developers', sa.Column('upgrade_reviewed_at', sa.DateTime()))
    op.add_column('isv_developers', sa.Column('upgrade_review_note', sa.String(500)))
    op.create_index('ix_isv_developers_status', 'isv_developers', ['status'])


def downgrade() -> None:
    op.drop_index('ix_isv_developers_status', 'isv_developers')
    for col in ['upgrade_review_note', 'upgrade_reviewed_at', 'upgrade_requested_at',
                'upgrade_request_reason', 'upgrade_request_tier',
                'verified_at', 'webhook_url', 'status']:
        op.drop_column('isv_developers', col)
