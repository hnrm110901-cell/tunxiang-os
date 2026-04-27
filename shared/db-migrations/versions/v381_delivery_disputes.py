"""Phase 2c: 外卖异议工作流 — delivery_disputes 表

自动裁决+人工复核:
  - ≤5000分(¥50)自动接受
  - >¥50转人工复核
  - 人工: 接受/拒绝/上报

状态机: pending → auto_accepted(≤¥50)
        pending → manual_review(>¥50) → accepted/rejected/escalated

表: delivery_disputes
  - 渠道(meituan/eleme/douyin)
  - 异议类型(refund/deduction/penalty/missing_item/quality/late_delivery/other)
  - 自动裁决(auto_accepted + reason)
  - 人工复核(reviewer_id/reviewed_at/review_note)
  - 证据(platform_evidence/store_evidence JSONB)
  - 结算金额(resolution_amount_fen)

RLS: 4条 PERMISSIVE + NULLIF + FORCE

Revision ID: v381_delivery_disputes
Revises: v380_invoice_ocr
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v381_delivery_disputes"
down_revision: Union[str, None] = "v380_invoice_ocr"
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
        CREATE TABLE IF NOT EXISTS delivery_disputes (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            order_id                UUID NOT NULL,

            channel                 VARCHAR(20) NOT NULL
                                        CHECK (channel IN ('meituan', 'eleme', 'douyin')),
            dispute_type            VARCHAR(30) NOT NULL
                                        CHECK (dispute_type IN (
                                            'refund', 'deduction', 'penalty',
                                            'missing_item', 'quality', 'late_delivery', 'other'
                                        )),
            platform_dispute_id     VARCHAR(50),
            disputed_amount_fen     INT NOT NULL,

            auto_accepted           BOOLEAN DEFAULT FALSE,
            auto_accept_reason      TEXT,

            status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                                        CHECK (status IN (
                                            'pending', 'auto_accepted', 'manual_review',
                                            'accepted', 'rejected', 'escalated'
                                        )),

            reviewer_id             UUID,
            reviewed_at             TIMESTAMPTZ,
            review_note             TEXT,

            platform_evidence       JSONB DEFAULT '{}'::JSONB,
            store_evidence          JSONB DEFAULT '{}'::JSONB,

            resolution_amount_fen   INT,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_tenant_store_status
            ON delivery_disputes (tenant_id, store_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_tenant_channel_created
            ON delivery_disputes (tenant_id, channel, created_at)
    """)

    # RLS
    _enable_rls("delivery_disputes")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_disputes CASCADE")
