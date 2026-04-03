"""v067 — 采购三单匹配引擎

新增表：
  purchase_invoices      — 采购发票（供应商开具给采购方的发票）
  purchase_match_records — 三单匹配结果记录

RLS 策略：标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）
金额单位：分（fen）

Revision ID: v067
Revises: v066
Create Date: 2026-03-31
"""

from alembic import op

revision = "v067"
down_revision = "v066"
branch_labels = None
depends_on = None

# 安全 RLS 条件（与 v056/v053 等一致）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id', TRUE)::UUID"
)


def _create_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DROP POLICY IF EXISTS {table}_select ON {table}; "
        f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"DROP POLICY IF EXISTS {table}_insert ON {table}; "
        f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"DROP POLICY IF EXISTS {table}_update ON {table}; "
        f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"DROP POLICY IF EXISTS {table}_delete ON {table}; "
        f"CREATE POLICY {table}_delete ON {table} FOR DELETE USING ({_SAFE_CONDITION})"
    )


def upgrade() -> None:
    # ── 采购发票表 ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS purchase_invoices (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            purchase_order_id   UUID        NOT NULL,
            supplier_id         UUID        DEFAULT NULL,
            store_id            UUID        DEFAULT NULL,
            invoice_no          VARCHAR(100) DEFAULT NULL,
            invoice_code        VARCHAR(50)  DEFAULT NULL,
            amount_fen          BIGINT      NOT NULL DEFAULT 0,
            tax_amount_fen      BIGINT      NOT NULL DEFAULT 0,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending',
            items               JSONB       NOT NULL DEFAULT '[]',
            issued_at           TIMESTAMPTZ DEFAULT NULL,
            verified_at         TIMESTAMPTZ DEFAULT NULL,
            notes               TEXT        DEFAULT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE purchase_invoices IS '采购发票（供应商→采购方），区别于 invoices 销售发票表';
        COMMENT ON COLUMN purchase_invoices.amount_fen IS '发票含税总额（分）';
        COMMENT ON COLUMN purchase_invoices.items IS '[{ingredient_name, qty, unit_price_fen, amount_fen}]';
        COMMENT ON COLUMN purchase_invoices.status IS 'pending/confirmed/rejected';

        CREATE INDEX IF NOT EXISTS idx_purchase_invoices_tenant_po
            ON purchase_invoices (tenant_id, purchase_order_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_purchase_invoices_tenant_supplier
            ON purchase_invoices (tenant_id, supplier_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_purchase_invoices_tenant_status
            ON purchase_invoices (tenant_id, status)
            WHERE is_deleted = FALSE;
    """)
    _create_rls("purchase_invoices")

    # ── 三单匹配结果表 ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS purchase_match_records (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            purchase_order_id   UUID        NOT NULL,
            supplier_id         UUID        DEFAULT NULL,
            store_id            UUID        DEFAULT NULL,
            status              VARCHAR(30) NOT NULL DEFAULT 'pending',
            po_amount_fen       BIGINT      NOT NULL DEFAULT 0,
            recv_amount_fen     BIGINT      NOT NULL DEFAULT 0,
            inv_amount_fen      BIGINT      DEFAULT NULL,
            variance_amount_fen BIGINT      NOT NULL DEFAULT 0,
            line_variances      JSONB       NOT NULL DEFAULT '[]',
            suggestion          TEXT        DEFAULT NULL,
            resolved_by         UUID        DEFAULT NULL,
            resolved_at         TIMESTAMPTZ DEFAULT NULL,
            resolution_note     TEXT        DEFAULT NULL,
            matched_at          TIMESTAMPTZ DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE purchase_match_records IS '采购三单（PO×收货×发票）匹配结果记录';
        COMMENT ON COLUMN purchase_match_records.status IS
            'pending/matched/quantity_variance/price_variance/missing_invoice/missing_receiving/multi_variance/auto_approved/resolved';
        COMMENT ON COLUMN purchase_match_records.variance_amount_fen IS '差异金额（分），matched时=0';
        COMMENT ON COLUMN purchase_match_records.line_variances IS '逐行差异明细 JSON 数组';
        COMMENT ON COLUMN purchase_match_records.suggestion IS 'AI 生成的差异处理建议（差异>500元时触发）';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_pmr_tenant_po_unique
            ON purchase_match_records (tenant_id, purchase_order_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_pmr_tenant_status
            ON purchase_match_records (tenant_id, status)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_pmr_tenant_supplier
            ON purchase_match_records (tenant_id, supplier_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS idx_pmr_tenant_variance_desc
            ON purchase_match_records (tenant_id, variance_amount_fen DESC)
            WHERE is_deleted = FALSE AND status NOT IN ('matched', 'auto_approved', 'resolved');
    """)
    _create_rls("purchase_match_records")


def downgrade() -> None:
    for table in ["purchase_match_records", "purchase_invoices"]:
        for op_name in ["delete", "update", "insert", "select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{op_name} ON {table}")
    op.execute("DROP TABLE IF EXISTS purchase_match_records")
    op.execute("DROP TABLE IF EXISTS purchase_invoices")
