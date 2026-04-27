"""v300 — 营销效果Worker桥接迁移

桥接迁移：v299_mkt_task_cal 的尾部链接。

Revision ID: v300_mkt_task_effect_worker
Revises: v299_mkt_task_cal
Create Date: 2026-04-24
"""
from alembic import op

revision = "v300_mkt_task_effect_worker"
down_revision = "v299_mkt_task_cal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
