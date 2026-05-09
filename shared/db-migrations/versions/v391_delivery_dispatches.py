"""Tier2: 配送调度持久化 — delivery_dispatches + delivery_provider_configs

将自营外卖配送调度（达达/顺丰/自有骑手）从内存存储迁移到 PostgreSQL。

表 1: delivery_dispatches
  订单 → 调度记录。每个外卖订单对应一条 dispatch 记录（含三方 provider_order_id、
  骑手位置、状态时间戳、回调 raw payload 等）。
  状态机: pending → dispatched → accepted → picked_up → delivering → delivered
  失败/取消支线: → cancelled / failed
  金额单位: 分（fen）

表 2: delivery_provider_configs
  租户 + 门店 + 配送商三元组的配置。包含 app_key / app_secret / 优先级 /
  callback_url 等。同 (tenant_id, store_id, provider) 唯一。
  app_secret 在应用层脱敏返回，DB 层加密存储留待后续 KMS 接入。

RLS: 4 条 PERMISSIVE + NULLIF + FORCE，与 v381_delivery_disputes 一致。

Revision ID: v391_delivery_dispatches
Revises: v390_api_key_system
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v391_delivery_dispatches"
down_revision: Union[str, None] = "v390_api_key_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    """为指定表创建完整 RLS（4条 PERMISSIVE + FORCE）。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy = f"rls_{table}_{action.lower()}"
        clause = "WITH CHECK" if action == "INSERT" else "USING"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"{clause} (tenant_id = {_RLS_EXPR})"
        )


def upgrade() -> None:
    # 类 A 副本去重 (B'-6, 2026-05-09): v216_delivery_dispatch.py 早建过
    # delivery_dispatches schema 不含 dispatch_no 列；本文件 IF NOT EXISTS 静默
    # 跳过 → CREATE INDEX dispatch_no 撞列。先 DROP CASCADE 再 CREATE，同 banquet 群模式。
    op.execute("DROP TABLE IF EXISTS delivery_dispatches CASCADE")
    # ── 1. delivery_dispatches ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_dispatches (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dispatch_no             VARCHAR(40) NOT NULL UNIQUE,
            tenant_id               UUID NOT NULL,
            store_id                VARCHAR(64) NOT NULL,
            order_id                VARCHAR(64) NOT NULL,

            provider                VARCHAR(20) NOT NULL
                                        CHECK (provider IN ('dada', 'shunfeng', 'self_rider')),
            provider_order_id       VARCHAR(64),

            status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                                        CHECK (status IN (
                                            'pending', 'dispatched', 'accepted',
                                            'picked_up', 'delivering', 'delivered',
                                            'cancelled', 'failed'
                                        )),

            rider_name              VARCHAR(50),
            rider_phone             VARCHAR(20),
            rider_lat               DOUBLE PRECISION,
            rider_lng               DOUBLE PRECISION,
            rider_updated_at        TIMESTAMPTZ,

            delivery_address        VARCHAR(500) NOT NULL,
            delivery_lat            DOUBLE PRECISION,
            delivery_lng            DOUBLE PRECISION,
            distance_meters         INT NOT NULL DEFAULT 0,
            delivery_fee_fen        INT NOT NULL DEFAULT 0,
            tip_fen                 INT NOT NULL DEFAULT 0,

            estimated_minutes       INT,
            actual_minutes          INT,

            dispatched_at           TIMESTAMPTZ,
            accepted_at             TIMESTAMPTZ,
            picked_up_at            TIMESTAMPTZ,
            delivered_at            TIMESTAMPTZ,
            cancelled_at            TIMESTAMPTZ,
            cancel_reason           VARCHAR(200),
            fail_reason             VARCHAR(200),

            kds_ready_at            TIMESTAMPTZ,
            rider_notified_at       TIMESTAMPTZ,

            provider_callback_raw   JSONB DEFAULT '{}'::JSONB,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_dispatches_tenant_store_status
            ON delivery_dispatches (tenant_id, store_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_dispatches_tenant_order
            ON delivery_dispatches (tenant_id, order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_dispatches_provider_order
            ON delivery_dispatches (provider, provider_order_id)
            WHERE provider_order_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_dispatches_dispatch_no
            ON delivery_dispatches (dispatch_no)
    """)

    _enable_rls("delivery_dispatches")

    # ── 2. delivery_provider_configs ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_provider_configs (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                VARCHAR(64) NOT NULL,

            provider                VARCHAR(20) NOT NULL
                                        CHECK (provider IN ('dada', 'shunfeng', 'self_rider')),
            enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
            priority                INT NOT NULL DEFAULT 99
                                        CHECK (priority >= 0 AND priority <= 99),

            app_key                 VARCHAR(200),
            app_secret              VARCHAR(200),
            merchant_id             VARCHAR(100),
            shop_no                 VARCHAR(100),
            callback_url            VARCHAR(500),
            extra_config            JSONB DEFAULT '{}'::JSONB,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,

            CONSTRAINT uniq_delivery_provider_per_store
                UNIQUE (tenant_id, store_id, provider)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_provider_configs_lookup
            ON delivery_provider_configs (tenant_id, store_id, enabled, priority)
    """)

    _enable_rls("delivery_provider_configs")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_provider_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS delivery_dispatches CASCADE")
