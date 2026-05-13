"""wine_storage 金额字段 Decimal 元 → BigInteger 分（CLAUDE.md §15+§17 Tier1 红线）

Revision ID: v415_wine_storage_amount_fen
Revises: v414_invoice_amount_fen
Create Date: 2026-05-07 (rebased onto v414 head 2026-05-13)

变更两张表：
  wine_storage_records.storage_price       NUMERIC(12,2) → storage_price_fen      BIGINT (NULLABLE)
  wine_storage_transactions.price_at_trans NUMERIC(12,2) → price_at_trans_fen    BIGINT (NULLABLE)

7 类流水（store_in/take_out/extend/transfer_in/transfer_out/write_off/adjustment）共用 price_at_trans_fen 字段。

迁移方案 A（单 PR 完成）：ADD fen 列 → backfill (yuan*100)::bigint → DROP 旧 yuan 列。
回滚反向。

关联：docs/gap-verification-2026-05-07.md Part E 第 2 项 + Part C §C.5
依赖：v414_invoice_amount_fen (rebase 2026-05-13 — #271 已 merge 进 main fbbb6e4f，串联同一 fen 整数规范)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v415_wine_storage_amount_fen"
down_revision: Union[str, Sequence[str], None] = "v414_invoice_amount_fen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── wine_storage_records.storage_price → storage_price_fen ────────────────
    op.add_column(
        "wine_storage_records",
        sa.Column("storage_price_fen", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE wine_storage_records "
        "SET storage_price_fen = (storage_price * 100)::bigint "
        "WHERE storage_price IS NOT NULL"
    )
    op.drop_column("wine_storage_records", "storage_price")

    # ── wine_storage_transactions.price_at_trans → price_at_trans_fen ─────────
    op.add_column(
        "wine_storage_transactions",
        sa.Column("price_at_trans_fen", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE wine_storage_transactions "
        "SET price_at_trans_fen = (price_at_trans * 100)::bigint "
        "WHERE price_at_trans IS NOT NULL"
    )
    op.drop_column("wine_storage_transactions", "price_at_trans")


def downgrade() -> None:
    # 反向：fen → 元 NUMERIC(12,2)
    op.add_column(
        "wine_storage_transactions",
        sa.Column("price_at_trans", sa.Numeric(12, 2), nullable=True),
    )
    op.execute(
        "UPDATE wine_storage_transactions "
        "SET price_at_trans = (price_at_trans_fen::numeric / 100) "
        "WHERE price_at_trans_fen IS NOT NULL"
    )
    op.drop_column("wine_storage_transactions", "price_at_trans_fen")

    op.add_column(
        "wine_storage_records",
        sa.Column("storage_price", sa.Numeric(12, 2), nullable=True),
    )
    op.execute(
        "UPDATE wine_storage_records "
        "SET storage_price = (storage_price_fen::numeric / 100) "
        "WHERE storage_price_fen IS NOT NULL"
    )
    op.drop_column("wine_storage_records", "storage_price_fen")
