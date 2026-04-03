"""v040: 渠道结算对账引擎 — platform_bills + settlement_discrepancies + receivable_forecasts

新增表：
  platform_bills               — 平台账单（美团/饿了么/抖音导入的对账账单）
  settlement_discrepancies     — 结算差异记录（平台账单 vs 系统订单逐单核对）
  receivable_forecasts         — 到账预测（基于 settlement_days 预测资金到账时间）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v040
Revises: v039
Create Date: 2026-03-30
"""

from alembic import op

revision = "v040"
down_revision = "v039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # platform_bills — 平台账单（从美团/饿了么/抖音导入的对账账单）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_bills (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            platform                VARCHAR(20) NOT NULL,
            bill_period             VARCHAR(20) NOT NULL,
            bill_type               VARCHAR(20) NOT NULL DEFAULT 'monthly',
            total_orders            INT         NOT NULL DEFAULT 0,
            gross_amount_fen        BIGINT      NOT NULL DEFAULT 0,
            commission_fen          BIGINT      NOT NULL DEFAULT 0,
            subsidy_fen             BIGINT      NOT NULL DEFAULT 0,
            other_deductions_fen    BIGINT      NOT NULL DEFAULT 0,
            actual_receive_fen      BIGINT      NOT NULL DEFAULT 0,
            bill_file_url           VARCHAR(500),
            raw_data                JSONB,
            status                  VARCHAR(20) NOT NULL DEFAULT 'imported',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, platform, bill_period),
            CONSTRAINT platform_bills_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            CONSTRAINT platform_bills_bill_type_check
                CHECK (bill_type IN ('monthly', 'weekly', 'daily')),
            CONSTRAINT platform_bills_status_check
                CHECK (status IN ('imported', 'reconciled', 'disputed'))
        );
    """)

    op.execute("ALTER TABLE platform_bills ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE platform_bills FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY platform_bills_{action.lower()}_tenant
                ON platform_bills
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_bills_tenant_store
            ON platform_bills (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_bills_tenant_store_platform
            ON platform_bills (tenant_id, store_id, platform);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_bills_status
            ON platform_bills (tenant_id, status);
    """)

    # ─────────────────────────────────────────────────────────────────
    # settlement_discrepancies — 结算差异记录（平台账单 vs 系统订单逐单核对）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS settlement_discrepancies (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            platform                VARCHAR(20) NOT NULL,
            bill_id                 UUID        REFERENCES platform_bills(id),
            platform_order_id       VARCHAR(100),
            internal_order_id       UUID,
            platform_amount_fen     INT,
            system_amount_fen       INT,
            diff_fen                INT GENERATED ALWAYS AS (platform_amount_fen - system_amount_fen) STORED,
            discrepancy_type        VARCHAR(30),
            status                  VARCHAR(20) NOT NULL DEFAULT 'open',
            resolved_at             TIMESTAMPTZ,
            resolved_by             UUID,
            resolve_note            TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT settlement_discrepancies_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            CONSTRAINT settlement_discrepancies_discrepancy_type_check
                CHECK (discrepancy_type IN (
                    'amount_mismatch',
                    'order_missing_in_system',
                    'order_missing_in_bill',
                    'commission_error'
                )),
            CONSTRAINT settlement_discrepancies_status_check
                CHECK (status IN ('open', 'resolved', 'disputed', 'waived'))
        );
    """)

    op.execute("ALTER TABLE settlement_discrepancies ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE settlement_discrepancies FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY settlement_discrepancies_{action.lower()}_tenant
                ON settlement_discrepancies
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_discrepancies_tenant_store
            ON settlement_discrepancies (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_discrepancies_bill_id
            ON settlement_discrepancies (bill_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_discrepancies_status
            ON settlement_discrepancies (tenant_id, store_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_settlement_discrepancies_platform_order
            ON settlement_discrepancies (platform, platform_order_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # receivable_forecasts — 到账预测（基于 settlement_days 预测到账时间）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS receivable_forecasts (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            platform                VARCHAR(20) NOT NULL,
            order_date              DATE        NOT NULL,
            expected_receive_date   DATE        NOT NULL,
            expected_amount_fen     BIGINT      NOT NULL,
            actual_amount_fen       BIGINT,
            actual_receive_date     DATE,
            status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, platform, order_date),
            CONSTRAINT receivable_forecasts_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            CONSTRAINT receivable_forecasts_status_check
                CHECK (status IN ('pending', 'received', 'overdue'))
        );
    """)

    op.execute("ALTER TABLE receivable_forecasts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE receivable_forecasts FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY receivable_forecasts_{action.lower()}_tenant
                ON receivable_forecasts
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_receivable_forecasts_tenant_store
            ON receivable_forecasts (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_receivable_forecasts_expected_date
            ON receivable_forecasts (tenant_id, store_id, expected_receive_date);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_receivable_forecasts_status
            ON receivable_forecasts (tenant_id, status, expected_receive_date);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS receivable_forecasts;")
    op.execute("DROP TABLE IF EXISTS settlement_discrepancies;")
    op.execute("DROP TABLE IF EXISTS platform_bills;")
