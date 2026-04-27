"""v118 — 预订渠道字段扩展

新增字段到 reservations 表：
  source_channel    — 预订来源渠道 ('meituan'/'dianping'/'wechat'/'phone'/'walkin')
  platform_order_id — 平台原始订单号（去重用）

新增唯一索引：
  uq_reservation_platform — (tenant_id, source_channel, platform_order_id) WHERE NOT NULL

用途：多平台Webhook聚合，防止同一平台订单重复写入。

Revision ID: v118
Revises: v117
Create Date: 2026-04-02
"""

from alembic import op

revision = "v118"
down_revision = "v117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 新增渠道字段 ────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE reservations
        ADD COLUMN IF NOT EXISTS source_channel VARCHAR(20) DEFAULT 'phone'
    """)

    op.execute("""
        ALTER TABLE reservations
        ADD COLUMN IF NOT EXISTS platform_order_id VARCHAR(100)
    """)

    # ── 去重唯一索引（仅对有 platform_order_id 的行生效） ───────────────────
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_reservation_platform
        ON reservations(tenant_id, source_channel, platform_order_id)
        WHERE platform_order_id IS NOT NULL
    """)

    # ── RLS 说明：reservations 表已在之前迁移中设置 RLS，此处无需重建 ────────


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_reservation_platform")
    op.execute("ALTER TABLE reservations DROP COLUMN IF EXISTS platform_order_id")
    op.execute("ALTER TABLE reservations DROP COLUMN IF EXISTS source_channel")
