"""v298 — 人群包Worker桥接迁移

桥接迁移：连接 v297_audience_pack → v299_mkt_task_cal 的迁移链。

Revision ID: v298_audience_pack_worker
Revises: v297_audience_pack
Create Date: 2026-04-24
"""
from alembic import op

revision = "v298_audience_pack_worker"
down_revision = "v297_audience_pack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
