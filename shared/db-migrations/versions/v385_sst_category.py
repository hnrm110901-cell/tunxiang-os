"""v385 — dishes 表新增 sst_category 字段

为菜品主档表增加 SST 分类字段，支持马来西亚/东南亚国家 SST（Sales & Service Tax）

  - standard (6%): 一般商品和服务（默认）
  - specific (8%): 石油产品、加工食品等特定品类
  - exempt   (0%): 豁免供应品

Revision ID: v385
Revises: v384
Create Date: 2026-05-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v385"
down_revision: Union[str, Sequence[str], None] = "v384"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column(
            "sst_category",
            sa.VARCHAR(20),
            nullable=True,
            server_default="standard",
            comment="SST分类: standard(6%)/specific(8%)/exempt(0%), NULL=默认standard",
        ),
    )


def downgrade() -> None:
    op.drop_column("dishes", "sst_category")
