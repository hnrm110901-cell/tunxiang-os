"""v422 — doc_number wave2 回填：`transfer_orders` 表新增 doc_number 字段

PRD-03 Wave2 方案 A（tx-supply 安全切片）：
为调拨单新增 doc_number 列，允许 NULL（兼容历史行）。
历史行回填为 'LEGACY-' + id 前 8 位，便于财务对账定位。

1 张表（Wave2 安全切片，3 callsite 接入）：
  1. transfer_orders  — 门店间库存调拨单

设计约束：
  - 不加 UNIQUE 约束（历史 LEGACY- 行 NULL 初态 → 回填后可能重复文件名）
  - 回填用 'LEGACY-' + substring(id::text, 1, 8) 格式
  - inspector-and-skip 防重运行（参考 v296 / v418 / v419 模式）
  - downgrade 反向 DROP COLUMN

⚠ down_revision 说明：
  本 PR 使用 v421_supplier_certificates 作为 down_revision（PRD-01 证件管理表），
  链路：v418 → v419 (Wave1) ／ v418 → v421 → v422 (Wave2)。
  两分支并存，无对应建表 migration 冲突。

⚠ 注意：`transfer_orders` 表 DDL 已在仓库历史 migration 中建立，
  本 migration 仅做 ADD COLUMN，无对应建表操作。

Revision ID: v422_doc_number_wave2_backfill
Revises: v421_supplier_certificates
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v422_doc_number_wave2_backfill"
down_revision: Union[str, Sequence[str], None] = "v421_supplier_certificates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "transfer_orders"


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if _TABLE not in existing_tables:
        return
    if _has_column(inspector, _TABLE, "doc_number"):
        return

    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN doc_number VARCHAR(64) NULL"
    )
    # 历史行回填：'LEGACY-' + id 前 8 位（id 必须为 UUID 类型）
    op.execute(
        f"""
        UPDATE {_TABLE}
        SET doc_number = 'LEGACY-' || substring(id::text, 1, 8)
        WHERE doc_number IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if _TABLE not in existing_tables:
        return
    if not _has_column(inspector, _TABLE, "doc_number"):
        return
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN doc_number")
