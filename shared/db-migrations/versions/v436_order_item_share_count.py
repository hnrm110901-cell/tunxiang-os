"""v436 — OrderItem.share_count 字段（PRD-11 sub-B / Phase 2 W11 第五发 / Tier 1 第 29 例）

业务背景：
  PRD-11 sub-A (v434 share_split_rules) 已配置层 — 每 dish 可设 allow_share + default_method
  + max_share_count，auto_deduction.deduct_for_dish/order 已加 share_split opt-in 参数。
  但 **caller 尚未传 share_split spec**, 整套"多人合点成本分摊"链路目前无 OrderItem 维度的
  人数数据。

  sub-B (本 PR) 范围:
    1. order_items.share_count INTEGER NOT NULL DEFAULT 1 (1=单人独享, N=N 人共享)
    2. cashier_engine.add_item / update_item 接受 kwonly share_count 参数 (默认 1)
    3. settle_order 后 fire-and-forget emit `OrderEventType.ITEMS_SETTLED` event 含
       items[] = [{order_item_id, dish_id, qty, share_count}], 留给 tx-supply projector
       (sub-B.2 / sub-C 范围) 异步消费触发 deduct_for_order(share_split=...).
       — 本 PR 不新增跨服务 import (Tier 1 边界不裂), 与 Phase 1 事件总线架构一致.
    4. settle 后 PATCH share_count 拒绝 (与 §17-A/B 终态保护一致, 走状态机守门)

  设计要点 (创始人 5/15 explicit OK 4+1 决策):
    - D1: 授权 + 改 entities.py (正统 Ontology 改动, 同步 entities.py + migration)
    - D2: NOT NULL DEFAULT 1 (历史 OrderItem 自动回填 1, 与 quantity NOT NULL 同模式)
    - D3: share_count>1 默认构造 share_split={method:'EVEN', count:N}
    - D4: settle 前 PATCH 可改, settle 后冻结 (与 §17 终态保护一致)
    - 范围: settle 后异步 emit_event, **不**新增 cashier_engine → auto_deduction 跨服务 import

  inspector-and-skip 模式 (与 v421+ 一致):
    - 表存在但列已存在 → 跳过 ADD COLUMN (test_migration_idempotent 友好)
    - 表不存在 → 跳过 (CI fresh-PG 测试不依赖 v001 全量重放)

Revision ID: v436_order_item_share_count
Revises: v435_market_survey_schema
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v436_order_item_share_count"
down_revision: Union[str, Sequence[str], None] = "v435_market_survey_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "order_items" not in existing_tables:
        return

    existing_cols = {c["name"] for c in inspector.get_columns("order_items")}
    if "share_count" in existing_cols:
        return

    # PostgreSQL 14+ 对 ALTER TABLE ADD COLUMN ... DEFAULT 是 O(1) 元数据操作,
    # catalog 维护 default 读时填值, 无需逐行 UPDATE. NOT NULL 守门同步生效.
    op.execute(
        "ALTER TABLE order_items ADD COLUMN share_count INTEGER NOT NULL DEFAULT 1"
    )

    # CHECK 约束 — share_count >= 1 (业务: 1 人最少, 0/负数禁止)
    # 与 sub-A share_split_rules.max_share_count CHECK >= 1 对齐
    existing_constraints = {
        c["name"] for c in inspector.get_check_constraints("order_items")
    }
    if "chk_order_items_share_count_positive" not in existing_constraints:
        op.execute(
            "ALTER TABLE order_items ADD CONSTRAINT chk_order_items_share_count_positive "
            "CHECK (share_count >= 1)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "order_items" not in existing_tables:
        return

    existing_cols = {c["name"] for c in inspector.get_columns("order_items")}
    if "share_count" not in existing_cols:
        return

    op.execute(
        "ALTER TABLE order_items DROP CONSTRAINT IF EXISTS chk_order_items_share_count_positive"
    )
    op.drop_column("order_items", "share_count")
