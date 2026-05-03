"""v386 — 微信支付营销活动表（WP-1 数据持久化）

存储微信支付营销活动配置（摇优惠/商家名片/投放计划），
当前 Phase 1 使用内存缓存，此表为 Phase 2 持久化做准备。

表: wechat_promotion_activities
  字段: id / tenant_id / store_id / activity_type / activity_name
        / wechat_activity_id / config(JSONB) / status / operator_id
        / begin_time / end_time / created_at / updated_at

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v386_wechat_promotion_activities
Revises: v385_unionid_indexes
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v386_wechat_promotion_activities"
down_revision: Union[str, None] = "v385_unionid_indexes"
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
        CREATE TABLE IF NOT EXISTS wechat_promotion_activities (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            activity_type       VARCHAR(30) NOT NULL
                                    CHECK (activity_type IN (
                                        'shake_coupon', 'merchant_card', 'promotion_plan'
                                    )),
            activity_name       VARCHAR(200) NOT NULL,
            wechat_activity_id  VARCHAR(64),
            config              JSONB DEFAULT '{}'::jsonb,
            status              VARCHAR(20) NOT NULL DEFAULT 'active'
                                    CHECK (status IN (
                                        'active', 'paused', 'ended', 'cancelled'
                                    )),
            operator_id         UUID,
            begin_time          TIMESTAMPTZ,
            end_time            TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wx_promo_act_tenant "
        "ON wechat_promotion_activities (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wx_promo_act_type "
        "ON wechat_promotion_activities (activity_type, tenant_id)"
    )
    _enable_rls("wechat_promotion_activities")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wechat_promotion_activities CASCADE")
