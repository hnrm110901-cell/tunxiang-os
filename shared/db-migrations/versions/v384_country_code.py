"""v384 — 核心业务表新增 country_code 字段

为所有核心业务表增加 country_code VARCHAR(10) NOT NULL DEFAULT 'CN'，
支持未来国际化多国家部署场景（如东南亚/北美门店）。

受影响表（按业务域分组）：
  - 顾客/门店/员工：customers, stores, employees
  - 菜品/分类：dishes, dish_categories, dish_ingredients
  - 订单：orders, order_items
  - 食材/库存：ingredient_masters, ingredients, ingredient_transactions
  - 收货/调拨：receiving_orders, receiving_order_items, transfer_orders, transfer_order_items
  - 组织：regions, brands

Revision ID: v384
Revises: v383
Create Date: 2026-05-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v384"
down_revision: Union[str, Sequence[str], None] = "v383_chain_consolidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─── 需要添加 country_code 的所有表 ──────────────────────────────────────────
TARGET_TABLES = [
    # 门店/顾客/员工（v001 核心实体）
    "customers",
    "stores",
    "employees",
    # 菜品域（v001 核心实体）
    "dishes",
    "dish_categories",
    "dish_ingredients",
    # 订单域（v001 核心实体）
    "orders",
    "order_items",
    # 食材域（v001 核心实体）
    "ingredient_masters",
    "ingredients",
    "ingredient_transactions",
    # 收货/调拨（v081）
    "receiving_orders",
    "receiving_order_items",
    "transfer_orders",
    "transfer_order_items",
    # 组织（v198）
    "regions",
    "brands",
]


def upgrade() -> None:
    for table in TARGET_TABLES:
        op.add_column(
            table,
            sa.Column(
                "country_code",
                sa.VARCHAR(10),
                nullable=False,
                server_default="CN",
                comment="国家/地区代码：CN=中国大陆，HK=香港，MO=澳门，SG=新加坡，MY=马来西亚，etc.",
            ),
        )


def downgrade() -> None:
    for table in reversed(TARGET_TABLES):
        op.drop_column(table, "country_code")
