"""v388_id_market — dishes 表新增 ppn_category 字段 + country_code ID 默认值

为菜品主档表增加 PPN（Pajak Pertambahan Nilai）分类字段，
支持印度尼西亚/东南亚国家增值税计算。

  - standard (11%): 一般商品和服务（默认，UU HPP 2022）
  - luxury   (12%): 奢侈品（计划中逐步实施）
  - export   (0%):  出口商品
  - exempt   (0%):  基本必需品、医疗、教育等

同时将 country_code 列默认值更新为 'ID' 相关表（如适用）。

Revision ID: v388_id_market
Revises: v387
Create Date: 2026-05-03

Chain repair (2026-05-09, B'): 原 revision = "v388" 与 v388_fill_rls_26_tables.py
  撞 ID（两文件同时声明 v388，alembic 拒绝加载）。本文件改为唯一 ID
  "v388_id_market"，并把 down_revision 从 filename stem "v387_pdpa_compliance"
  订正为真 revision ID "v387"。链路：v387 → v388_id_market → v388 (fill_rls)
  → v389_vn_market（v388 fill_rls 的 down_revision 同步改为 "v388_id_market"）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v388_id_market"
down_revision: Union[str, Sequence[str], None] = "v387"
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
