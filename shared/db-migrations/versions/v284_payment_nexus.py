"""v206 — tx-pay 支付中枢基础表

新增表：
  - payment_channel_configs  — 多租户支付渠道配置（路由引擎依赖）
  - payment_sagas            — 支付Saga事务日志（崩溃恢复依赖）
  - payment_idempotency      — 幂等键去重记录

设计原则：
  - 所有表包含 tenant_id + RLS 策略
  - 金额单位：分（BIGINT）
  - 配合 tx-pay (:8013) 服务使用

Revision ID: v206c
Revises: v205
Create Date: 2026-04-11
"""

from alembic import op

revision = "v206c"
down_revision = "v205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. 支付渠道配置表 ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_channel_configs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            brand_id        UUID,
            store_id        UUID,
            method          VARCHAR(30) NOT NULL,
            channel_name    VARCHAR(50) NOT NULL,
            priority        INTEGER NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            config_data     JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,

            UNIQUE (tenant_id, COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::UUID), method)
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcc_tenant_method
            ON payment_channel_configs (tenant_id, method)
            WHERE is_active = TRUE AND is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcc_tenant_store
            ON payment_channel_configs (tenant_id, store_id)
            WHERE is_active = TRUE AND is_deleted = FALSE
    """)

    # RLS
    op.execute("ALTER TABLE payment_channel_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payment_channel_configs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY pcc_select ON payment_channel_configs FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pcc_insert ON payment_channel_configs FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pcc_update ON payment_channel_configs FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pcc_delete ON payment_channel_configs FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)

    # ─── 2. 支付Saga事务日志 ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_sagas (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            order_id        VARCHAR(100) NOT NULL,
            step            VARCHAR(30) NOT NULL DEFAULT 'validating',
            amount_fen      BIGINT NOT NULL DEFAULT 0,
            method          VARCHAR(30) NOT NULL,
            payment_id      VARCHAR(100),
            trade_no        VARCHAR(100),
            idempotency_key VARCHAR(200),
            error_msg       TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ps_tenant_order
            ON payment_sagas (tenant_id, order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ps_stale
            ON payment_sagas (step, updated_at)
            WHERE step IN ('executing', 'confirming')
    """)

    # RLS
    op.execute("ALTER TABLE payment_sagas ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payment_sagas FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY ps_select ON payment_sagas FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY ps_insert ON payment_sagas FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY ps_update ON payment_sagas FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY ps_delete ON payment_sagas FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)

    # ─── 3. 幂等键去重记录 ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_idempotency (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            idempotency_key VARCHAR(200) NOT NULL,
            tenant_id       UUID NOT NULL,
            payment_id      VARCHAR(100) NOT NULL,
            status          VARCHAR(30) NOT NULL,
            trade_no        VARCHAR(100),
            amount_fen      BIGINT NOT NULL DEFAULT 0,
            channel_data    JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (idempotency_key, tenant_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pi_key_tenant
            ON payment_idempotency (idempotency_key, tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pi_expire
            ON payment_idempotency (created_at)
    """)

    # RLS
    op.execute("ALTER TABLE payment_idempotency ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payment_idempotency FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY pi_select ON payment_idempotency FOR SELECT
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pi_insert ON payment_idempotency FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pi_update ON payment_idempotency FOR UPDATE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)
    op.execute("""
        CREATE POLICY pi_delete ON payment_idempotency FOR DELETE
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::UUID
                AND current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
            )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_idempotency CASCADE")
    op.execute("DROP TABLE IF EXISTS payment_sagas CASCADE")
    op.execute("DROP TABLE IF EXISTS payment_channel_configs CASCADE")
