"""v071: 资金分账表 — 分账规则 / 分账流水 / 结算批次

新增表：
  split_rules         — 分账规则（平台费/品牌费/加盟商分成）
  split_ledgers       — 分账流水（每笔订单分账明细）
  settlement_batches  — 结算批次（按周期汇总结算）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v071
Revises: v070
Create Date: 2026-03-31
"""

from alembic import op

revision = "v071"
down_revision = "v070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # split_rules — 分账规则
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_rules (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            rule_type         VARCHAR(30) NOT NULL,
            rate_permil       INTEGER     NOT NULL DEFAULT 0,
            fixed_fee_fen     INTEGER     NOT NULL DEFAULT 0,
            effective_from    DATE        NOT NULL,
            effective_to      DATE,
            is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE split_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE split_rules FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY split_rules_{action.lower()}_tenant ON split_rules
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant
            ON split_rules (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant_store
            ON split_rules (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_rules_tenant_type
            ON split_rules (tenant_id, rule_type);
    """)

    # ─────────────────────────────────────────────────────────────────
    # split_ledgers — 分账流水
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_ledgers (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            order_id             UUID        NOT NULL,
            payment_id           UUID,
            store_id             UUID        NOT NULL,
            total_amount_fen     INTEGER     NOT NULL,
            platform_fee_fen     INTEGER     NOT NULL DEFAULT 0,
            brand_royalty_fen    INTEGER     NOT NULL DEFAULT 0,
            franchise_share_fen  INTEGER     NOT NULL DEFAULT 0,
            net_settlement_fen   INTEGER     NOT NULL DEFAULT 0,
            status               VARCHAR(20) NOT NULL DEFAULT 'pending',
            settled_at           TIMESTAMPTZ,
            batch_id             UUID,
            is_deleted           BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE split_ledgers ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE split_ledgers FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY split_ledgers_{action.lower()}_tenant ON split_ledgers
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant
            ON split_ledgers (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_order
            ON split_ledgers (tenant_id, order_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_store
            ON split_ledgers (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_status
            ON split_ledgers (tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_ledgers_tenant_batch
            ON split_ledgers (tenant_id, batch_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # settlement_batches — 结算批次
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS settlement_batches (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            batch_no          VARCHAR(50) NOT NULL UNIQUE,
            period_start      DATE        NOT NULL,
            period_end        DATE        NOT NULL,
            store_id          UUID        NOT NULL,
            total_orders      INTEGER     NOT NULL DEFAULT 0,
            total_amount_fen  INTEGER     NOT NULL DEFAULT 0,
            total_split_fen   INTEGER     NOT NULL DEFAULT 0,
            status            VARCHAR(20) NOT NULL DEFAULT 'draft',
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE settlement_batches ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE settlement_batches FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY settlement_batches_{action.lower()}_tenant ON settlement_batches
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant
            ON settlement_batches (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_store
            ON settlement_batches (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_status
            ON settlement_batches (tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_batches_tenant_batch_no
            ON settlement_batches (tenant_id, batch_no);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS split_ledgers CASCADE;")
    op.execute("DROP TABLE IF EXISTS settlement_batches CASCADE;")
    op.execute("DROP TABLE IF EXISTS split_rules CASCADE;")
