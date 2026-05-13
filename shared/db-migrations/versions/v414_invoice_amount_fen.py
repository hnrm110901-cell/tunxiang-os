"""invoice 金额字段 Decimal 元 → BigInteger 分（CLAUDE.md §15+§17 Tier1 红线）

Revision ID: v414_invoice_amount_fen
Revises: v413_member_identity_map
Create Date: 2026-05-07 (rebased onto v413 head 2026-05-13)

变更：
  invoices.amount       NUMERIC(10,2) → invoices.amount_fen BIGINT (NOT NULL)
  invoices.tax_amount   NUMERIC(10,2) → invoices.tax_fen    BIGINT (NULLABLE)

迁移方案 B（PR #264/#271 verifier 反馈，**保留旧列一个发布周期**）：
  1. ADD COLUMN amount_fen BIGINT, tax_fen BIGINT (nullable)
  2. NULL 守门：拒绝 amount IS NULL 的脏数据（先人工处理才能继续）
  3. UPDATE 回填：amount_fen = ROUND(amount * 100)::bigint
                  tax_fen   = ROUND(tax_amount * 100)::bigint WHERE NOT NULL
  4. SET amount_fen NOT NULL
  5. RENAME 旧列：amount → amount_legacy_yuan, tax_amount → tax_amount_legacy_yuan
     —— 不直接 DROP，保留至少一个发布周期作为可观察、可回滚的桥
     —— 旧列消除留 v40X+1 PR（待生产验证 fen 写读路径稳定后）

回滚（downgrade）：
  - 重命名旧列回原名
  - 把 fen 数据回填到旧列（仅在不可逆 DROP 之前可全量回滚）

关联：docs/gap-verification-2026-05-07.md Part E 第 1 项 + Part C §C.6
依赖：v413_member_identity_map（rebase 2026-05-13 main b37e50aa head）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v414_invoice_amount_fen"
down_revision: Union[str, Sequence[str], None] = "v413_member_identity_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 加 fen 列（先 nullable，方便回填）
    op.add_column(
        "invoices",
        sa.Column("amount_fen", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_fen", sa.BigInteger(), nullable=True),
    )

    # 2. NULL 守门：amount 历史列原本未声明 NOT NULL，存量脏数据需先清理
    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM invoices WHERE amount IS NULL")
    ).scalar()
    if null_count and null_count > 0:
        raise RuntimeError(
            f"v414_invoice_amount_fen abort: invoices 表有 {null_count} 行 amount IS NULL，"
            f"违反 NOT NULL 约束预期。请先人工 backfill 或删除这些记录。"
        )

    # 3. 回填：用 ROUND() 与 service _yuan_to_fen ROUND_HALF_UP 一致
    #    （金税四期/诺诺惯例 "四舍五入"，避免银行家舍入造成 .005 边界差异）
    op.execute(
        "UPDATE invoices SET amount_fen = (ROUND(amount * 100))::bigint"
    )
    op.execute(
        "UPDATE invoices SET tax_fen = (ROUND(tax_amount * 100))::bigint "
        "WHERE tax_amount IS NOT NULL"
    )

    # 4. amount_fen NOT NULL 守门
    op.alter_column("invoices", "amount_fen", nullable=False)

    # 5. RENAME 旧列（不 DROP）— 保留一个发布周期作为可逆桥
    #    旧列消除走 v40X+1 PR，等生产验证 fen 写读路径稳定后
    op.execute("ALTER TABLE invoices RENAME COLUMN amount TO amount_legacy_yuan")
    op.execute("ALTER TABLE invoices RENAME COLUMN tax_amount TO tax_amount_legacy_yuan")


def downgrade() -> None:
    # 反向 RENAME：amount_legacy_yuan → amount, tax_amount_legacy_yuan → tax_amount
    op.execute("ALTER TABLE invoices RENAME COLUMN amount_legacy_yuan TO amount")
    op.execute("ALTER TABLE invoices RENAME COLUMN tax_amount_legacy_yuan TO tax_amount")

    # 兜底：若旧列回填后被改动过，用最新 fen 数据覆盖（保最终一致）
    op.execute("UPDATE invoices SET amount = (amount_fen::numeric / 100)")
    op.execute(
        "UPDATE invoices SET tax_amount = (tax_fen::numeric / 100) "
        "WHERE tax_fen IS NOT NULL"
    )

    op.drop_column("invoices", "amount_fen")
    op.drop_column("invoices", "tax_fen")
