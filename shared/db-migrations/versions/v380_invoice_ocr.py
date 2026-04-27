"""Phase 2b: 金税四期OCR发票识别 — invoice_ocr_results 表

支持多OCR提供商(腾讯云/阿里云/百度云)识别发票,结构化提取+SHA-256去重+验真。

表: invoice_ocr_results
  - OCR识别结果(代码/号码/日期/金额/税额/购销方/明细)
  - 去重hash(SHA-256: 发票代码+号码+金额)
  - 验真状态(pending/verified/failed/duplicate)
  - 置信度评分(0-1)

RLS: 4条 PERMISSIVE + NULLIF + FORCE

Revision ID: v380_invoice_ocr
Revises: v379_dynamic_pricing_ai
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v380_invoice_ocr"
down_revision: Union[str, None] = "v379_dynamic_pricing_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    """为指定表创建完整 RLS（4条 PERMISSIVE + FORCE）。"""
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
        CREATE TABLE IF NOT EXISTS invoice_ocr_results (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            invoice_id              UUID,

            image_url               TEXT NOT NULL,
            ocr_provider            VARCHAR(20) DEFAULT 'tencent'
                                        CHECK (ocr_provider IN ('tencent', 'aliyun', 'baidu')),
            ocr_raw_json            JSONB,

            invoice_code            VARCHAR(20),
            invoice_number          VARCHAR(20),
            invoice_date            DATE,
            seller_name             VARCHAR(200),
            seller_tax_no           VARCHAR(20),
            buyer_name              VARCHAR(200),
            buyer_tax_no            VARCHAR(20),

            total_amount_fen        BIGINT,
            tax_amount_fen          BIGINT,
            items                   JSONB DEFAULT '[]'::JSONB,

            verification_status     VARCHAR(20) DEFAULT 'pending'
                                        CHECK (verification_status IN (
                                            'pending', 'verified', 'failed', 'duplicate'
                                        )),
            verification_result     JSONB,
            is_duplicate            BOOLEAN DEFAULT FALSE,
            duplicate_hash          VARCHAR(64),
            confidence_score        NUMERIC(3,2),

            created_at              TIMESTAMPTZ DEFAULT NOW(),
            updated_at              TIMESTAMPTZ DEFAULT NOW(),
            is_deleted              BOOLEAN DEFAULT FALSE,

            CONSTRAINT uq_invoice_ocr_tenant_hash
                UNIQUE (tenant_id, duplicate_hash)
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_tenant
            ON invoice_ocr_results (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_invoice
            ON invoice_ocr_results (invoice_id)
            WHERE invoice_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_status
            ON invoice_ocr_results (verification_status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_hash
            ON invoice_ocr_results (duplicate_hash)
            WHERE duplicate_hash IS NOT NULL
    """)

    # RLS
    _enable_rls("invoice_ocr_results")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_ocr_results CASCADE")
