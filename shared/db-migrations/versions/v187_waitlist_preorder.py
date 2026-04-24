"""v187 — 排队预点菜 + 消费返现 + 第N份折扣 + 餐位费路由

变更：
  waitlist_entries — 新增 pre_order_items JSONB 字段
  waitlist_entries — 新增 pre_order_total_fen BIGINT 字段
  waitlist_entries — 新增 coupon_issued_on_timeout BOOLEAN 字段

Revision: v187
"""

from alembic import op

revision = "v187b"
down_revision = "v187"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS pre_order_items JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS pre_order_total_fen BIGINT DEFAULT 0")
    op.execute("ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS coupon_issued_on_timeout BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE waitlist_entries DROP COLUMN IF EXISTS pre_order_items")
    op.execute("ALTER TABLE waitlist_entries DROP COLUMN IF EXISTS pre_order_total_fen")
    op.execute("ALTER TABLE waitlist_entries DROP COLUMN IF EXISTS coupon_issued_on_timeout")
