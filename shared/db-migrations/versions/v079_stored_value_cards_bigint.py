"""v075 — 储值卡金额列升级为 BIGINT + 补充标准 card_type 枚举约束

背景：
  v015/v022 建立了 stored_value_cards / stored_value_transactions 体系，
  金额列使用 INTEGER（最大约 21 亿分 = 2100 万元）。
  大型连锁企业（徐记海鲜规模）企业卡余额可能超过 INTEGER 上限，
  本迁移将所有金额列升级为 BIGINT 以消除溢出风险。

同时补充：
  - stored_value_cards.card_type 新增 standard/enterprise 取值说明（注释）
  - stored_value_cards 中增加 frozen_by_id 索引（freeze_by_id 操作优化）
  - stored_value_transactions 中补充 store_id 索引

RLS：复用已有策略（v015 + v006 安全模式），不重建。

Revision ID: v075
Revises: v074
Create Date: 2026-03-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v079"
down_revision = "v078"
branch_labels = None
depends_on = None

# 需要升级为 BIGINT 的 (表, 列) 对
_BIGINT_COLUMNS = [
    # stored_value_cards
    ("stored_value_cards", "balance_fen"),
    ("stored_value_cards", "gift_balance_fen"),
    ("stored_value_cards", "main_balance_fen"),
    ("stored_value_cards", "total_recharged_fen"),
    ("stored_value_cards", "total_consumed_fen"),
    ("stored_value_cards", "total_refunded_fen"),
    # stored_value_transactions
    ("stored_value_transactions", "amount_fen"),
    ("stored_value_transactions", "main_amount_fen"),
    ("stored_value_transactions", "gift_amount_fen"),
    ("stored_value_transactions", "balance_after_fen"),
    ("stored_value_transactions", "gift_balance_after_fen"),
    # stored_value_recharge_plans
    ("stored_value_recharge_plans", "recharge_amount_fen"),
    ("stored_value_recharge_plans", "gift_amount_fen"),
]


def upgrade() -> None:
    # ── 1. 金额列 INTEGER → BIGINT ──────────────────────────────────
    for table, column in _BIGINT_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.BigInteger(),
            existing_type=sa.Integer(),
            existing_nullable=False,
        )

    # ── 2. 补充 store_id 索引（stored_value_transactions）──────────
    # 收银查询"本店流水"场景的性能优化
    op.create_index(
        "idx_svt_store_id",
        "stored_value_transactions",
        ["store_id", "created_at"],
        postgresql_where=sa.text("store_id IS NOT NULL"),
    )

    # ── 3. card_type 添加注释（standard / gift / enterprise）────────
    # PostgreSQL 不支持 ALTER COLUMN ... COMMENT，用 COMMENT ON COLUMN 语法
    op.execute(
        "COMMENT ON COLUMN stored_value_cards.card_type IS "
        "'standard=标准储值卡 | gift=礼品卡 | enterprise=企业卡 | personal=个人(v1遗留)'"
    )


def downgrade() -> None:
    # 删除补充索引
    op.drop_index("idx_svt_store_id", table_name="stored_value_transactions")

    # BIGINT → INTEGER 回滚（注意：若数据超出 INTEGER 范围将失败）
    for table, column in reversed(_BIGINT_COLUMNS):
        op.alter_column(
            table,
            column,
            type_=sa.Integer(),
            existing_type=sa.BigInteger(),
            existing_nullable=False,
        )
