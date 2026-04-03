"""v070: 供应商门户表 — 账户 / 报价 / 对账

新增表：
  supplier_accounts        — 供应商账户
  supplier_quotations      — 供应商报价
  supplier_reconciliations — 对账记录

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v070
Revises: v046
Create Date: 2026-03-31
"""

from alembic import op

revision = "v070"
down_revision = "v046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # supplier_accounts — 供应商账户
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_accounts (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            name              VARCHAR(200) NOT NULL,
            category          VARCHAR(50)  NOT NULL,
            contact           JSONB        NOT NULL DEFAULT '{}',
            certifications    JSONB        NOT NULL DEFAULT '[]',
            payment_terms     VARCHAR(30)  NOT NULL DEFAULT 'net30',
            status            VARCHAR(30)  NOT NULL DEFAULT 'active',
            overall_score     FLOAT        NOT NULL DEFAULT 0.0,
            order_count       INTEGER      NOT NULL DEFAULT 0,
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE supplier_accounts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE supplier_accounts FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY supplier_accounts_{action.lower()}_tenant ON supplier_accounts
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_accounts_tenant
            ON supplier_accounts (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_accounts_tenant_category
            ON supplier_accounts (tenant_id, category);
    """)

    # ─────────────────────────────────────────────────────────────────
    # supplier_quotations — 供应商报价
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_quotations (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            supplier_id       UUID        NOT NULL REFERENCES supplier_accounts(id),
            rfq_id            VARCHAR(50)  NOT NULL,
            item_name         VARCHAR(200) NOT NULL,
            quantity          NUMERIC(12,3) NOT NULL,
            delivery_date     DATE,
            unit_price_fen    INTEGER      NOT NULL DEFAULT 0,
            total_price_fen   INTEGER      NOT NULL DEFAULT 0,
            delivery_days     INTEGER      NOT NULL DEFAULT 0,
            notes             TEXT,
            status            VARCHAR(30)  NOT NULL DEFAULT 'open',
            composite_score   FLOAT        NOT NULL DEFAULT 0.0,
            score_detail      JSONB,
            submitted_at      TIMESTAMPTZ,
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE supplier_quotations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE supplier_quotations FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY supplier_quotations_{action.lower()}_tenant ON supplier_quotations
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_quotations_tenant
            ON supplier_quotations (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_quotations_rfq
            ON supplier_quotations (tenant_id, rfq_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_quotations_supplier
            ON supplier_quotations (tenant_id, supplier_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # supplier_reconciliations — 对账记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_reconciliations (
            id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID        NOT NULL,
            supplier_id           UUID        NOT NULL REFERENCES supplier_accounts(id),
            record_type           VARCHAR(30) NOT NULL,
            reference_id          VARCHAR(100),
            store_id              UUID,
            ingredient_name       VARCHAR(200),
            on_time               BOOLEAN,
            quality_result        VARCHAR(30),
            price_adherence       BOOLEAN,
            price_competitiveness FLOAT,
            service_rating        FLOAT,
            price_fen             INTEGER,
            total_fen             INTEGER,
            contract_data         JSONB,
            record_date           DATE,
            extra                 JSONB,
            is_deleted            BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE supplier_reconciliations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE supplier_reconciliations FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY supplier_reconciliations_{action.lower()}_tenant ON supplier_reconciliations
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_reconciliations_tenant
            ON supplier_reconciliations (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_reconciliations_supplier
            ON supplier_reconciliations (tenant_id, supplier_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_reconciliations_type
            ON supplier_reconciliations (tenant_id, record_type);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_supplier_reconciliations_store
            ON supplier_reconciliations (tenant_id, store_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supplier_reconciliations CASCADE;")
    op.execute("DROP TABLE IF EXISTS supplier_quotations CASCADE;")
    op.execute("DROP TABLE IF EXISTS supplier_accounts CASCADE;")
