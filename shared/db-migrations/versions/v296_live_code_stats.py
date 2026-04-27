"""v296 — 活码统计桥接迁移

桥接迁移：连接 v295_live_code → v297_audience_pack 的迁移链。

Revision ID: v296_live_code_stats
Revises: v295_live_code
Create Date: 2026-04-24
"""
from alembic import op

revision = "v296_live_code_stats"
down_revision = "v295_live_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
