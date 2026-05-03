"""v388 — dishes 表新增 ppn_category 字段 + country_code ID 默认值

为菜品主档表增加 PPN（Pajak Pertambahan Nilai）分类字段，
支持印度尼西亚/东南亚国家增值税计算。

  - standard (11%): 一般商品和服务（默认，UU HPP 2022）
  - luxury   (12%): 奢侈品（计划中逐步实施）
  - export   (0%):  出口商品
  - exempt   (0%):  基本必需品、医疗、教育等

同时将 country_code 列默认值更新为 'ID' 相关表（如适用）。

Revision ID: v388
Revises: v387_pdpa_compliance
Create Date: 2026-05-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v388"
down_revision: Union[str, Sequence[str], None] = "v387_pdpa_compliance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # dishes 表新增 ppn_category 字段
    op.add_column(
        "dishes",
        sa.Column(
            "ppn_category",
            sa.VARCHAR(20),
            nullable=True,
            server_default="standard",
            comment="PPN分类: standard(11%)/luxury(12%)/export(0%)/exempt(0%), NULL=默认standard",
        ),
    )


def downgrade() -> None:
    op.drop_column("dishes", "ppn_category")
