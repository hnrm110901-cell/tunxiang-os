"""v158 — 菜品多规格支持（大份/中份/小份/半份）

在 dishes 表新增 specifications JSONB 字段，存储规格列表。
格式: [{"spec_id": "s1", "name": "大份", "price_fen": 8800}, ...]

Revision ID: v158
Revises: v157
Create Date: 2026-04-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v158"
down_revision: Union[str, None] = "v157"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column(
            "specifications",
            sa.JSON(),
            server_default="[]",
            nullable=True,
            comment="规格列表[{spec_id,name,price_fen,is_half}]",
        ),
    )


def downgrade() -> None:
    op.drop_column("dishes", "specifications")
