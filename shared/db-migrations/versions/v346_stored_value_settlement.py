"""v346: 储值分账结算 — 跨店分账规则 / 分账流水 / 结算批次

新增表：
  stored_value_split_rules   — 跨店消费分账比例规则（充值店/消费店/总部三方）
  stored_value_split_ledger  — 储值跨店分账流水（每笔消费拆分明细）
  sv_settlement_batches      — 储值分账结算批次（按周期汇总结算）

RLS 策略：全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE）

Revision ID: v346_stored_value_settlement
Revises: v344_banquet_aftercare
Create Date: 2026-04-25
"""

from alembic import op

revision = "v346_stored_value_settlement"
down_revision = "v345_temp_practice"
branch_labels = None
depends_on = None

_NEW_TABLES = [
    "stored_value_split_rules",
    "stored_value_split_ledger",
    "sv_settlement_batches",
]

_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_safe_rls(table_name: str) -> None:
    """v006+ safe RLS: 4 policies + NULL guard + FORCE"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        (
            "update",
            f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})",
        ),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def upgrade() -> None:
    # ── 1. stored_value_split_rules — 跨店分账规则 ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stored_value_split_rules (
            id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,

            rule_name               VARCHAR(100)    NOT NULL,
            recharge_store_ratio    DECIMAL(5,4)    NOT NULL DEFAULT 0.1500,
            consume_store_ratio     DECIMAL(5,4)    NOT NULL DEFAULT 0.7000,
            hq_ratio                DECIMAL(5,4)    NOT NULL DEFAULT 0.1500,
            scope_type              VARCHAR(20)     NOT NULL DEFAULT 'brand',
            applicable_store_ids    UUID[],
            is_default              BOOLEAN         NOT NULL DEFAULT FALSE,
            effective_from          DATE,
            effective_to            DATE,

            CONSTRAINT chk_sv_split_ratios_sum
                CHECK (recharge_store_ratio + consume_store_ratio + hq_ratio = 1.0000)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_rules_tenant
            ON stored_value_split_rules (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_rules_tenant_default
            ON stored_value_split_rules (tenant_id, is_default)
            WHERE is_default = TRUE AND is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_rules_tenant_scope
            ON stored_value_split_rules (tenant_id, scope_type)
    """)

    # ── 2. stored_value_split_ledger — 分账流水 ───────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stored_value_split_ledger (
            id                          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID            NOT NULL,
            created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN         NOT NULL DEFAULT FALSE,

            transaction_id              UUID            NOT NULL,
            rule_id                     UUID            NOT NULL REFERENCES stored_value_split_rules(id),
            recharge_store_id           UUID            NOT NULL,
            consume_store_id            UUID            NOT NULL,
            total_amount_fen            BIGINT          NOT NULL,
            recharge_store_amount_fen   BIGINT          NOT NULL,
            consume_store_amount_fen    BIGINT          NOT NULL,
            hq_amount_fen              BIGINT          NOT NULL,
            settlement_status           VARCHAR(20)     NOT NULL DEFAULT 'pending',
            settlement_batch_id         UUID,
            settled_at                  TIMESTAMPTZ,

            CONSTRAINT chk_sv_ledger_status
                CHECK (settlement_status IN ('pending', 'settled', 'disputed'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_tenant
            ON stored_value_split_ledger (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_tenant_txn
            ON stored_value_split_ledger (tenant_id, transaction_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_tenant_status
            ON stored_value_split_ledger (tenant_id, settlement_status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_recharge_store
            ON stored_value_split_ledger (tenant_id, recharge_store_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_consume_store
            ON stored_value_split_ledger (tenant_id, consume_store_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_split_ledger_batch
            ON stored_value_split_ledger (settlement_batch_id)
            WHERE settlement_batch_id IS NOT NULL
    """)

    # ── 3. sv_settlement_batches — 结算批次 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sv_settlement_batches (
            id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,

            batch_no            VARCHAR(30)     NOT NULL UNIQUE,
            period_start        DATE            NOT NULL,
            period_end          DATE            NOT NULL,
            total_records       INT             NOT NULL DEFAULT 0,
            total_amount_fen    BIGINT          NOT NULL DEFAULT 0,
            status              VARCHAR(20)     NOT NULL DEFAULT 'draft',

            CONSTRAINT chk_sv_batch_status
                CHECK (status IN ('draft', 'confirmed', 'settled', 'disputed'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_settlement_batches_tenant
            ON sv_settlement_batches (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_settlement_batches_tenant_status
            ON sv_settlement_batches (tenant_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sv_settlement_batches_batch_no
            ON sv_settlement_batches (tenant_id, batch_no)
    """)

    # ── 启用 RLS ─────────────────────────────────────────────────────────
    for table in _NEW_TABLES:
        _enable_safe_rls(table)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(
                f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}"
            )
    op.execute("DROP TABLE IF EXISTS stored_value_split_ledger CASCADE")
    op.execute("DROP TABLE IF EXISTS sv_settlement_batches CASCADE")
    op.execute("DROP TABLE IF EXISTS stored_value_split_rules CASCADE")
