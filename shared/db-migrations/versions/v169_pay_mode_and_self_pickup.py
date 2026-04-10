"""v169 — 多渠道完整支撑：先付/后付区域 + 自提渠道

新增字段：
  table_zones.pay_mode          — 区域支付时序：prepay(先付)/postpay(后付)，默认postpay
  dining_sessions.pay_mode      — 会话支付时序（继承区域，可覆盖）
  dining_sessions.order_type    — 会话渠道类型（dine_in/takeout/self_pickup/banquet）
  orders.pickup_code            — 自提取餐码（4-6位，当日唯一）
  orders.pickup_ready_at        — 备餐完成时间（KDS finish后回填）
  orders.pickup_confirmed_at    — 顾客取餐确认时间
  orders.pickup_channel         — 自提渠道来源：miniapp/h5/wechat/store

场景说明：
  先付区域（prepay）：顾客扫码点餐 → 立即支付 → KDS出品 → 叫号取餐
  后付区域（postpay）：开台 → 就餐 → 买单 → 结账（传统堂食）
  混合门店：大厅快餐区=prepay，包间区=postpay，互不干扰

Revision ID: v169
Revises: v168
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v169"
down_revision: Union[str, None] = "v168"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. table_zones.pay_mode ─────────────────────────────────────────────
    if not _col_exists("table_zones", "pay_mode"):
        op.add_column(
            "table_zones",
            sa.Column(
                "pay_mode", sa.String(20), nullable=False, server_default="postpay",
                comment="区域支付时序：prepay=先付后餐(快餐/外带) / postpay=先餐后付(堂食默认)",
            ),
        )
        op.execute("""
            ALTER TABLE table_zones
            ADD CONSTRAINT ck_table_zones_pay_mode
            CHECK (pay_mode IN ('prepay', 'postpay'));
        """)

    # ── 2. dining_sessions.pay_mode ─────────────────────────────────────────
    if not _col_exists("dining_sessions", "pay_mode"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "pay_mode", sa.String(20), nullable=False, server_default="postpay",
                comment="会话支付时序（继承table_zones.pay_mode，开台时写入，可管理员覆盖）",
            ),
        )

    # ── 3. dining_sessions.order_type ───────────────────────────────────────
    # 记录本会话的渠道类型，与orders.order_type保持一致（避免联表）
    if not _col_exists("dining_sessions", "order_type"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "order_type", sa.String(30), nullable=False, server_default="dine_in",
                comment="会话渠道：dine_in/takeout/self_pickup/banquet",
            ),
        )

    # ── 4. dining_sessions.prepay_order_id ──────────────────────────────────
    # 先付场景：扫码下单后立即生成支付单，结算时关联到会话
    if not _col_exists("dining_sessions", "prepay_order_id"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "prepay_order_id", UUID(as_uuid=True), nullable=True,
                comment="先付场景的预支付订单ID（扫码点餐→支付→出品流程中写入）",
            ),
        )

    # ── 5. orders.pickup_code ───────────────────────────────────────────────
    if not _col_exists("orders", "pickup_code"):
        op.add_column(
            "orders",
            sa.Column(
                "pickup_code", sa.String(10), nullable=True,
                comment="自提取餐码（4-6位字母数字，当日门店唯一，用于叫号/扫码提货）",
            ),
        )
        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_pickup_code_store_date
            ON orders (store_id, pickup_code, DATE(created_at AT TIME ZONE 'UTC'))
            WHERE pickup_code IS NOT NULL AND is_deleted = false;
        """)

    # ── 6. orders.pickup_ready_at ───────────────────────────────────────────
    if not _col_exists("orders", "pickup_ready_at"):
        op.add_column(
            "orders",
            sa.Column(
                "pickup_ready_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="备餐完成时间（KDS所有任务done后回填，触发叫号/推送）",
            ),
        )

    # ── 7. orders.pickup_confirmed_at ───────────────────────────────────────
    if not _col_exists("orders", "pickup_confirmed_at"):
        op.add_column(
            "orders",
            sa.Column(
                "pickup_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="顾客取餐确认时间（员工扫码确认 or 自助取餐后写入）",
            ),
        )

    # ── 8. orders.pickup_channel ─────────────────────────────────────────────
    if not _col_exists("orders", "pickup_channel"):
        op.add_column(
            "orders",
            sa.Column(
                "pickup_channel", sa.String(20), nullable=True,
                comment="自提渠道来源：miniapp/h5/wechat/store(收银台代下单)",
            ),
        )

    # ── 9. 索引：按门店+pickup_code快速查找自提单 ─────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_orders_pickup_ready
        ON orders (store_id, pickup_ready_at)
        WHERE pickup_ready_at IS NOT NULL
          AND pickup_confirmed_at IS NULL
          AND is_deleted = false;
    """)


def downgrade() -> None:
    for col in ("pickup_channel", "pickup_confirmed_at", "pickup_ready_at", "pickup_code"):
        op.execute(sa.text(f"ALTER TABLE orders DROP COLUMN IF EXISTS {col};"))

    for col in ("prepay_order_id", "order_type", "pay_mode"):
        op.execute(sa.text(f"ALTER TABLE dining_sessions DROP COLUMN IF EXISTS {col};"))

    op.execute(sa.text(
        "ALTER TABLE table_zones DROP CONSTRAINT IF EXISTS ck_table_zones_pay_mode;"
    ))
    op.execute(sa.text("ALTER TABLE table_zones DROP COLUMN IF EXISTS pay_mode;"))
