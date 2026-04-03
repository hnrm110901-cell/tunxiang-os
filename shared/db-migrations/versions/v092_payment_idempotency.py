"""v092: 支付幂等性 — payments表添加idempotency_key列

在现有 payments 表添加 idempotency_key 列，并建唯一索引防止重复扣款。

设计要点：
  - idempotency_key 可为 NULL（兼容旧客户端，不做幂等保护）
  - 唯一约束范围：(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL
  - 跨租户相同 key 互不影响（不同 tenant_id）
  - 并发写入相同 key 时，DB 层 UNIQUE 约束保证只有一条记录落盘
  - 幂等键有效期由业务层约定（24小时），DB 索引不自动清理

依赖：
  - v091 由 payment_saga 智能体创建（payment_saga 表），本迁移依赖它
  - 若 v091 尚未合并，可临时将 down_revision 改为 v090 后人工校正链路

Revision ID: v092
Revises: v091
Create Date: 2026-03-31
"""

from alembic import op

revision = "v092"
down_revision = "v091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 添加幂等键列 ─────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE payments
          ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128)
    """)

    # ── 唯一索引：同一租户+同一幂等键只能有一条支付记录 ─────────────────
    # 注意：WHERE idempotency_key IS NOT NULL 使 NULL 值不参与唯一约束
    # （旧客户端不传 key 时不受影响）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_idempotency
          ON payments(tenant_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL
    """)

    # ── 辅助查询索引（幂等命中查询走此索引） ─────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_payments_idempotency_key
          ON payments(tenant_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payments_idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_payment_idempotency")
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS idempotency_key")
