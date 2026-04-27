"""发票采集系统：发票主档 + 明细行
Tables: invoices, invoice_items
Sprint: P0-S4

Revision ID: v238
Revises: v237
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v238b"
down_revision = "v238"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()
    if "invoices" in existing:
        return

    # ──────────────────────────────────────────────────────────────────
    # invoices — 发票主档
    # 记录每张发票的 OCR 识别结果、金税四期核验状态及集团级去重信息
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            brand_id                UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            uploader_id             UUID        NOT NULL,
            application_id          UUID        REFERENCES expense_applications(id),

            -- 发票基础信息（OCR识别结果）
            invoice_type            VARCHAR(20) NOT NULL DEFAULT 'vat_general',
            invoice_code            VARCHAR(20),
            invoice_number          VARCHAR(20),
            invoice_date            DATE,
            seller_name             VARCHAR(200),
            seller_tax_id           VARCHAR(20),
            buyer_name              VARCHAR(200),
            buyer_tax_id            VARCHAR(20),
            total_amount            BIGINT,
            tax_amount              BIGINT,
            amount_without_tax      BIGINT,
            tax_rate                NUMERIC(5,4),

            -- 文件存储
            file_url                TEXT        NOT NULL,
            file_name               VARCHAR(255) NOT NULL,
            file_type               VARCHAR(20) NOT NULL DEFAULT 'image/jpeg',
            file_size               INTEGER,
            thumbnail_url           TEXT,

            -- OCR 核验状态
            ocr_status              VARCHAR(20) NOT NULL DEFAULT 'pending',
            ocr_provider            VARCHAR(20),
            ocr_raw_result          JSONB,
            ocr_confidence          NUMERIC(4,3),

            -- 金税四期核验
            verify_status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            verify_at               TIMESTAMPTZ,
            verify_response         JSONB,

            -- 集团级去重
            dedup_hash              VARCHAR(64),
            is_duplicate            BOOLEAN     DEFAULT false,
            duplicate_of_id         UUID        REFERENCES invoices(id),

            -- 科目归类（A2 Agent自动建议）
            suggested_category_id   UUID        REFERENCES expense_categories(id),
            confirmed_category_id   UUID        REFERENCES expense_categories(id),
            category_confidence     NUMERIC(4,3),

            -- 合规
            is_within_period        BOOLEAN,
            compliance_notes        TEXT,

            created_at              TIMESTAMPTZ DEFAULT now(),
            updated_at              TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE invoices IS
            '发票主档：记录每张上传发票的 OCR 识别结果、金税四期核验状态、集团去重信息及科目归类建议';

        COMMENT ON COLUMN invoices.store_id IS
            '上传发票的门店ID，对应门店维度汇总统计';
        COMMENT ON COLUMN invoices.uploader_id IS
            '上传人员工ID，对应 employees.id';
        COMMENT ON COLUMN invoices.application_id IS
            '关联的费用申请ID；可为 NULL，支持先上传发票后再关联申请单的工作流';
        COMMENT ON COLUMN invoices.invoice_type IS
            '发票类型：vat_special=增值税专票 / vat_general=增值税普票 / quota=定额发票 / receipt=收据 / other=其他';
        COMMENT ON COLUMN invoices.total_amount IS
            '价税合计，单位：分(fen)，展示时除以100转元';
        COMMENT ON COLUMN invoices.tax_amount IS
            '税额，单位：分(fen)，展示时除以100转元';
        COMMENT ON COLUMN invoices.amount_without_tax IS
            '不含税金额，单位：分(fen)，展示时除以100转元';
        COMMENT ON COLUMN invoices.tax_rate IS
            '税率，如 0.0600 表示6%';
        COMMENT ON COLUMN invoices.file_type IS
            '文件 MIME 类型：image/jpeg / image/png / application/pdf';
        COMMENT ON COLUMN invoices.file_size IS
            '文件字节数';
        COMMENT ON COLUMN invoices.thumbnail_url IS
            '缩略图 URL，P1 阶段由后端异步生成';
        COMMENT ON COLUMN invoices.ocr_status IS
            'OCR 识别状态：pending=待识别 / processing=识别中 / success=识别成功 / failed=识别失败';
        COMMENT ON COLUMN invoices.ocr_provider IS
            'OCR 服务商：baidu=百度 / aliyun=阿里云';
        COMMENT ON COLUMN invoices.ocr_raw_result IS
            'OCR 原始返回结果完整 JSON，用于问题排查和重新解析';
        COMMENT ON COLUMN invoices.ocr_confidence IS
            'OCR 综合置信度，范围 0.000–1.000';
        COMMENT ON COLUMN invoices.verify_status IS
            '金税四期核验状态：pending=待核验 / verified_real=核验真实 / verified_fake=核验为假 / verify_failed=核验接口失败 / skipped=跳过核验';
        COMMENT ON COLUMN invoices.verify_response IS
            '金税四期接口原始返回 JSON，用于合规存档';
        COMMENT ON COLUMN invoices.dedup_hash IS
            '去重哈希，SHA-256(invoice_code + invoice_number + total_amount)；集团级去重核心依据';
        COMMENT ON COLUMN invoices.is_duplicate IS
            '是否为重复发票；true 时 duplicate_of_id 指向原始发票';
        COMMENT ON COLUMN invoices.duplicate_of_id IS
            '重复的原始发票ID，is_duplicate=true 时必填';
        COMMENT ON COLUMN invoices.suggested_category_id IS
            'A2 Agent 自动建议的会计科目ID，对应 expense_categories.id';
        COMMENT ON COLUMN invoices.confirmed_category_id IS
            '人工确认的会计科目ID，优先级高于 suggested_category_id';
        COMMENT ON COLUMN invoices.category_confidence IS
            'A2 Agent 科目建议置信度，范围 0.000–1.000';
        COMMENT ON COLUMN invoices.is_within_period IS
            '发票日期是否在费用报销周期内；由 A2 Agent 在关联申请单时自动校验';
        COMMENT ON COLUMN invoices.compliance_notes IS
            '合规备注，由 A2 Agent 填写，如"发票日期超出报销周期30天"';

        -- 集团去重核心索引（partial index，dedup_hash IS NOT NULL 时才唯一）
        CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_tenant_dedup_hash
            ON invoices (tenant_id, dedup_hash)
            WHERE dedup_hash IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_invoices_tenant_store_verify
            ON invoices (tenant_id, store_id, verify_status);

        CREATE INDEX IF NOT EXISTS ix_invoices_tenant_application
            ON invoices (tenant_id, application_id);

        CREATE INDEX IF NOT EXISTS ix_invoices_tenant_invoice_date
            ON invoices (tenant_id, invoice_date);

        CREATE INDEX IF NOT EXISTS ix_invoices_tenant_is_duplicate
            ON invoices (tenant_id, is_duplicate);

        CREATE INDEX IF NOT EXISTS ix_invoices_tenant_seller_tax_id
            ON invoices (tenant_id, seller_tax_id);
    """)

    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invoices FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY invoices_rls ON invoices
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # invoice_items — 发票明细行
    # 每张发票对应一至多条明细，ON DELETE CASCADE 随主档删除
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            invoice_id  UUID        NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            item_name   VARCHAR(200) NOT NULL,
            item_spec   VARCHAR(100),
            unit        VARCHAR(20),
            quantity    NUMERIC(12,4),
            unit_price  BIGINT,
            amount      BIGINT      NOT NULL,
            tax_rate    NUMERIC(5,4),
            tax_amount  BIGINT,
            created_at  TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE invoice_items IS
            '发票明细行：OCR 识别出的发票货物或应税劳务明细，随主档 invoices 级联删除';

        COMMENT ON COLUMN invoice_items.invoice_id IS
            '所属发票ID，ON DELETE CASCADE；一张发票对应一至多条明细行';
        COMMENT ON COLUMN invoice_items.item_name IS
            '货物或应税劳务、服务名称';
        COMMENT ON COLUMN invoice_items.item_spec IS
            '规格型号，如"500ml"；可为 NULL';
        COMMENT ON COLUMN invoice_items.unit IS
            '计量单位，如"箱"/"个"；可为 NULL';
        COMMENT ON COLUMN invoice_items.quantity IS
            '数量，支持小数（如 2.5000）；可为 NULL';
        COMMENT ON COLUMN invoice_items.unit_price IS
            '不含税单价，单位：分(fen)，展示时除以100转元；可为 NULL';
        COMMENT ON COLUMN invoice_items.amount IS
            '金额（不含税），单位：分(fen)，展示时除以100转元';
        COMMENT ON COLUMN invoice_items.tax_rate IS
            '税率，如 0.0600 表示6%；可为 NULL（定额票等无明细税率）';
        COMMENT ON COLUMN invoice_items.tax_amount IS
            '税额，单位：分(fen)，展示时除以100转元；可为 NULL';

        CREATE INDEX IF NOT EXISTS ix_invoice_items_tenant_invoice
            ON invoice_items (tenant_id, invoice_id);
    """)

    op.execute("ALTER TABLE invoice_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invoice_items FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY invoice_items_rls ON invoice_items
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)


def downgrade() -> None:
    # 按依赖反向顺序删除（先删叶子表，再删被引用表）

    # invoice_items（引用 invoices）
    op.execute("DROP POLICY IF EXISTS invoice_items_rls ON invoice_items;")
    op.execute("DROP TABLE IF EXISTS invoice_items CASCADE;")

    # invoices（被 invoice_items 引用，最后删）
    op.execute("DROP POLICY IF EXISTS invoices_rls ON invoices;")
    op.execute("DROP TABLE IF EXISTS invoices CASCADE;")
