"""v079: 为 stores 表添加固定成本配置列

为 P&L 损益表的经营费用摊销提供专用字段。

新增列（stores 表）：
  - monthly_rent_fen        BIGINT DEFAULT 0  — 月租金（分）
  - monthly_utility_fen     BIGINT DEFAULT 0  — 月水电费（分）
  - monthly_other_fixed_fen BIGINT DEFAULT 0  — 月其他固定费（分）

同时更新 stores 的 RLS 策略（继承已有的 SELECT/INSERT/UPDATE/DELETE）。

Revision ID: v079
Revises: v078
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "v083"
down_revision: Union[str, None] = "v082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 添加专用固定成本列 ────────────────────────────────────
    op.execute("""
        ALTER TABLE stores
          ADD COLUMN IF NOT EXISTS monthly_rent_fen        BIGINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS monthly_utility_fen     BIGINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS monthly_other_fixed_fen BIGINT NOT NULL DEFAULT 0;
    """)

    # ── 约束：不允许负值 ──────────────────────────────────────
    op.execute("""
        ALTER TABLE stores
          ADD CONSTRAINT chk_monthly_rent_fen_gte_0
            CHECK (monthly_rent_fen >= 0),
          ADD CONSTRAINT chk_monthly_utility_fen_gte_0
            CHECK (monthly_utility_fen >= 0),
          ADD CONSTRAINT chk_monthly_other_fixed_fen_gte_0
            CHECK (monthly_other_fixed_fen >= 0);
    """)

    # ── 从已有 config JSONB 迁移历史数据（如果有）─────────────
    op.execute("""
        UPDATE stores
        SET
          monthly_rent_fen = COALESCE(
            (config->'fixed_costs'->>'monthly_rent_fen')::BIGINT, 0
          ),
          monthly_utility_fen = COALESCE(
            (config->'fixed_costs'->>'monthly_utility_fen')::BIGINT, 0
          ),
          monthly_other_fixed_fen = COALESCE(
            (config->'fixed_costs'->>'monthly_other_fixed_fen')::BIGINT, 0
          )
        WHERE config IS NOT NULL
          AND jsonb_exists(config::jsonb, 'fixed_costs');
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE stores
          DROP CONSTRAINT IF EXISTS chk_monthly_rent_fen_gte_0,
          DROP CONSTRAINT IF EXISTS chk_monthly_utility_fen_gte_0,
          DROP CONSTRAINT IF EXISTS chk_monthly_other_fixed_fen_gte_0;
    """)
    op.execute("""
        ALTER TABLE stores
          DROP COLUMN IF EXISTS monthly_rent_fen,
          DROP COLUMN IF EXISTS monthly_utility_fen,
          DROP COLUMN IF EXISTS monthly_other_fixed_fen;
    """)
