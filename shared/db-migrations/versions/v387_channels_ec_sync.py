"""v387 — 视频号小店订单同步表（VC-1 数据持久化）

存储从视频号小店（Channels EC）同步的订单数据，
与 tx-trade 内部订单表通过 order_mapping 关联。

表: channels_ec_orders
  字段: id / tenant_id / store_id
        / channel_order_id / status / event_type
        / raw_body(JSONB) / internal_order_id
        / error_log / synced_at / created_at / updated_at

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v387_channels_ec_sync
Revises: v386_wechat_promotion_activities
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v387_channels_ec_sync"
down_revision: Union[str, None] = "v386_wechat_promotion_activities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy = f"rls_{table}_{action.lower()}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR})"
        )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS channels_ec_orders (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            channel_order_id    VARCHAR(64) NOT NULL,
            status              VARCHAR(30) NOT NULL DEFAULT 'pending_payment'
                                    CHECK (status IN (
                                        'pending_payment', 'paid', 'preparing',
                                        'completed', 'cancelled', 'refunded'
                                    )),
            event_type          VARCHAR(40) NOT NULL DEFAULT 'order_create'
                                    CHECK (event_type IN (
                                        'order_create', 'order_pay', 'order_refund',
                                        'order_cancel', 'order_delivery'
                                    )),
            raw_body            JSONB DEFAULT '{}'::jsonb,
            internal_order_id   UUID,
            error_log           TEXT,
            synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_channels_ec_orders_tenant
        ON channels_ec_orders (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_channels_ec_orders_channel_order_id
        ON channels_ec_orders (channel_order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_channels_ec_orders_internal_order_id
        ON channels_ec_orders (internal_order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_channels_ec_orders_status
        ON channels_ec_orders (status)
    """)

    _enable_rls("channels_ec_orders")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channels_ec_orders CASCADE")
