"""invoice 金额字段 Decimal 元 → BigInteger 分（CLAUDE.md §15+§17 Tier1 红线）

Revision ID: v403
Revises: v402
Create Date: 2026-05-07

变更：
  invoices.amount       NUMERIC(10,2) → invoices.amount_fen BIGINT (NOT NULL)
  invoices.tax_amount   NUMERIC(10,2) → invoices.tax_fen    BIGINT (NULLABLE)

迁移步骤（方案 A — 单 PR 完成，假设 invoices 表数据量较小，
徐记/czyz/zqx/sgc 当前都未上电子发票生产数据）：
  1. ADD COLUMN amount_fen BIGINT, tax_fen BIGINT
  2. UPDATE 回填：amount_fen = (amount * 100)::bigint
  3. SET amount_fen NOT NULL
  4. DROP COLUMN amount, tax_amount

回滚反向，downgrade 用 amount_fen 重建 NUMERIC(10,2) 列。

关联：docs/gap-verification-2026-05-07.md Part E 第 1 项 + Part C §C.6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v403"
down_revision: Union[str, Sequence[str], None] = "v402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 加 fen 列（先 nullable，方便回填）
    op.add_column(
        "invoices",
        sa.Column("amount_fen", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_fen", sa.BigInteger(), nullable=True),
    )

    # 2. 回填：amount * 100 → amount_fen（int 强制截断保 fen 精度）
    op.execute("UPDATE invoices SET amount_fen = (amount * 100)::bigint")
    op.execute(
        "UPDATE invoices SET tax_fen = (tax_amount * 100)::bigint "
        "WHERE tax_amount IS NOT NULL"
    )

    # 3. amount_fen NOT NULL 守门
    op.alter_column("invoices", "amount_fen", nullable=False)

    # 4. 删旧 Decimal 列（避免 fen / 元 共存歧义）
    op.drop_column("invoices", "amount")
    op.drop_column("invoices", "tax_amount")


def downgrade() -> None:
    # 反向：fen → 元 NUMERIC(10,2)
    op.add_column(
        "invoices",
        sa.Column("amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_amount", sa.Numeric(10, 2), nullable=True),
    )

    op.execute("UPDATE invoices SET amount = (amount_fen::numeric / 100)")
    op.execute(
        "UPDATE invoices SET tax_amount = (tax_fen::numeric / 100) "
        "WHERE tax_fen IS NOT NULL"
    )

    op.alter_column("invoices", "amount", nullable=False)

    op.drop_column("invoices", "amount_fen")
    op.drop_column("invoices", "tax_fen")
