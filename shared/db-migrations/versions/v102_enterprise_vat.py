"""v102: 企业增值税申报 — 销项税/进项税/月度申报

新建 2 张表：
  vat_declarations    — 增值税申报单（月度/季度，含销项/进项/应纳税额）
  vat_input_invoices  — 进项发票台账（供应商增值税专票，用于抵扣销项税）

设计要点：
  - output_tax_fen 从当期订单收入自动计算（tax_rate 默认 6%，可配置）
  - input_tax_fen 从录入的进项发票汇总
  - payable_tax_fen = output_tax_fen - input_tax_fen（非负）
  - vat_declarations 状态机: draft → reviewing → filed → paid
  - vat_input_invoices 状态: pending → verified / rejected
  - 唯一约束 (tenant_id, store_id, period) 防重复申报

与诺诺对接：
  - filed 时调用诺诺 API（实际对接由上层 service 控制）
  - 本迁移只建表结构

Revision ID: v102
Revises: v101
Create Date: 2026-04-01
"""

from alembic import op

revision = "v102"
down_revision = "v101b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. vat_declarations — 增值税申报单 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS vat_declarations (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            store_id            UUID         NOT NULL,
            period              VARCHAR(10)  NOT NULL,
            period_type         VARCHAR(10)  NOT NULL DEFAULT 'monthly'
                                    CHECK (period_type IN ('monthly','quarterly')),
            tax_rate            NUMERIC(5,4) NOT NULL DEFAULT 0.06,
            gross_revenue_fen   BIGINT       NOT NULL DEFAULT 0,
            output_tax_fen      BIGINT       NOT NULL DEFAULT 0,
            input_tax_fen       BIGINT       NOT NULL DEFAULT 0,
            payable_tax_fen     BIGINT       NOT NULL DEFAULT 0,
            paid_tax_fen        BIGINT       NOT NULL DEFAULT 0,
            status              VARCHAR(20)  NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft','reviewing','filed','paid')),
            filed_at            TIMESTAMPTZ,
            paid_at             TIMESTAMPTZ,
            nuonuo_declaration_no VARCHAR(50),
            note                TEXT,
            created_by          UUID,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, period)
        )
    """)
    op.execute("ALTER TABLE vat_declarations ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY vat_declarations_rls ON vat_declarations
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vat_declarations_store_period
            ON vat_declarations(tenant_id, store_id, period)
    """)

    # ── 2. vat_input_invoices — 进项发票台账 ─────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS vat_input_invoices (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            declaration_id   UUID         NOT NULL REFERENCES vat_declarations(id),
            invoice_no       VARCHAR(30)  NOT NULL,
            invoice_date     DATE         NOT NULL,
            supplier_name    VARCHAR(200) NOT NULL,
            supplier_tax_no  VARCHAR(30),
            amount_fen       BIGINT       NOT NULL,
            tax_rate         NUMERIC(5,4) NOT NULL DEFAULT 0.06,
            input_tax_fen    BIGINT       NOT NULL,
            invoice_type     VARCHAR(30)  NOT NULL DEFAULT 'vat_special',
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','verified','rejected')),
            verified_at      TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, declaration_id, invoice_no)
        )
    """)
    op.execute("ALTER TABLE vat_input_invoices ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY vat_input_invoices_rls ON vat_input_invoices
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vat_input_invoices_declaration
            ON vat_input_invoices(tenant_id, declaration_id, status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vat_input_invoices CASCADE")
    op.execute("DROP TABLE IF EXISTS vat_declarations CASCADE")
