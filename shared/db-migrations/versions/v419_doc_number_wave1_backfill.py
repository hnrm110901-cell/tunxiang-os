"""v419 — doc_number wave1 回填：4 类高频单据 doc_number 字段

PRD-03 Wave1：为 4 类高频单据新增 doc_number 列，允许 NULL（兼容历史行）。
历史行回填为 'LEGACY-' + id 前 8 位，便于财务对账定位。

4 类单据（原计划 5 类，§19 P0#2 移除申购单，留给 PRD-07）：
  1. purchase_orders     — 采购单（po_number 保留，双轨兼容期）
  2. stocktakes          — 盘点单（v064 创建）
  3. receiving_orders    — 收货单（ORM entity）
  4. ingredient_transactions — 出入库流水

申购单（requisitions）移除原因：仓库内无 CREATE TABLE requisitions migration，
申购 service 是纯内存字典实现。建表 + 持久化 + doc_number 接入留给 PRD-07
申购模板系统（Phase 2 W9-W12 范围）。

设计约束：
  - 不加 UNIQUE 约束（历史 LEGACY- 行 NULL 初态 → 回填后可能重复文件名）
  - 回填用 'LEGACY-' + substring(id::text, 1, 8) 格式
  - inspector-and-skip 防重运行（参考 v296 / v418 模式）
  - downgrade 反向 DROP COLUMN

Revision ID: v419_doc_number_wave1_backfill
Revises: v418_doc_number_rules
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v419_doc_number_wave1_backfill"
down_revision: Union[str, Sequence[str], None] = "v418_doc_number_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = [
    "purchase_orders",
    # §19 P0#2：requisitions 表在仓库内无 CREATE TABLE migration（申购单 service
    # 是纯内存字典实现），故移除。申购单 doc_number 接入留给 PRD-07 申购模板系统时
    # 一并做（建表 + service 持久化 + doc_number 接入）。
    "stocktakes",
    "receiving_orders",
    "ingredient_transactions",
]


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            continue
        if _has_column(inspector, table, "doc_number"):
            continue

        op.execute(
            f"ALTER TABLE {table} ADD COLUMN doc_number VARCHAR(64) NULL"
        )
        # 历史行回填：'LEGACY-' + id 前 8 位（id 必须为 UUID 类型）
        op.execute(
            f"""
            UPDATE {table}
            SET doc_number = 'LEGACY-' || substring(id::text, 1, 8)
            WHERE doc_number IS NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            continue
        if not _has_column(inspector, table, "doc_number"):
            continue
        op.execute(f"ALTER TABLE {table} DROP COLUMN doc_number")
