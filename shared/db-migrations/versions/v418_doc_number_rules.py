"""v418 — doc_number_rules + doc_number_sequences：业务单号定制规则引擎

PRD-03（README §三）核心基础设施：17 类单据可读单号生成器。
财务对账 / 食药监稽查 / 银行流水匹配场景要求人类可读单号
（如 PO20260513-001 vs 9f3a-...UUID）。本表存模板规则与并发安全的序号计数器。

设计要点：
  1. doc_number_rules — 配置：tenant_id + doc_type → template + seq_scope
       - 系统默认模板：tenant_id = '00000000-0000-0000-0000-000000000000'（特殊 UUID）
       - tenant 覆盖：tenant_id = 实际租户 → 优先于系统默认
       - 决策记录（创始人授权 2026-05-14 Q4）：双层 fallback

  2. doc_number_sequences — 状态：tenant_id + doc_type + scope_key → current_seq
       - scope_key 形态：
           * global  → 固定字符串 'global'
           * daily   → 'YYYY-MM-DD'
           * monthly → 'YYYY-MM'
           * store   → store_id UUID
       - 并发安全：应用层 SELECT pg_advisory_xact_lock(SHA256[:8])
         + INSERT ... ON CONFLICT DO UPDATE current_seq = current_seq + 1
         参考 v296 api_idempotency_cache + services/tx-trade/api_idempotency.py

  3. RLS：
       - tenant_id 列 + 系统默认 tenant '00...000' 通过 RLS bypass
       - bypass 通过 `current_setting('app.tenant_id')` 比对 + OR 加 system tenant
         注：系统默认行只 read，不 mutate

  4. 17 类 doc_type 枚举（v419 / v420 wave 回填）：
       purchase_order / requisition / stocktake / transfer / receiving /
       inventory_io / quality_check / waste / supplier_audit / member_topup /
       order / invoice / wine_storage / refund / payment / settlement / adjustment

Revision ID: v418_doc_number_rules
Revises: v417_grabfood_enum_shrink
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v418_doc_number_rules"
down_revision: Union[str, Sequence[str], None] = "v417_grabfood_enum_shrink"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "doc_number_rules" not in existing:
        op.execute(
            """
            CREATE TABLE doc_number_rules (
                tenant_id     UUID         NOT NULL,
                doc_type      VARCHAR(48)  NOT NULL,
                template      VARCHAR(128) NOT NULL,
                seq_scope     VARCHAR(16)  NOT NULL
                    CHECK (seq_scope IN ('global', 'daily', 'monthly', 'store')),
                is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
                description   TEXT,
                created_by    UUID,
                created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, doc_type)
            )
            """
        )
        op.execute("ALTER TABLE doc_number_rules ENABLE ROW LEVEL SECURITY")
        # 租户隔离 + 系统默认 tenant 全租户可读（fallback）
        op.execute(
            f"""
            CREATE POLICY doc_number_rules_tenant_isolation
            ON doc_number_rules
            USING (
                tenant_id::text = current_setting('app.tenant_id', true)
                OR tenant_id = '{SYSTEM_TENANT_ID}'::uuid
            )
            WITH CHECK (
                tenant_id::text = current_setting('app.tenant_id', true)
            )
            """
        )

    if "doc_number_sequences" not in existing:
        op.execute(
            """
            CREATE TABLE doc_number_sequences (
                tenant_id     UUID         NOT NULL,
                doc_type      VARCHAR(48)  NOT NULL,
                scope_key     VARCHAR(64)  NOT NULL,
                current_seq   BIGINT       NOT NULL DEFAULT 0,
                last_used_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, doc_type, scope_key)
            )
            """
        )
        op.execute("ALTER TABLE doc_number_sequences ENABLE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY doc_number_sequences_tenant_isolation
            ON doc_number_sequences
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_doc_number_seq_last_used
            ON doc_number_sequences (tenant_id, doc_type, last_used_at DESC)
            """
        )

    # 系统默认模板（创始人决策 Q4：双层 fallback）
    op.execute(
        f"""
        INSERT INTO doc_number_rules (tenant_id, doc_type, template, seq_scope, description)
        VALUES
            ('{SYSTEM_TENANT_ID}', 'purchase_order',  'PO{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '采购单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'requisition',     'RQ{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '申购单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'stocktake',       'STK-{{yyyy}}{{MM}}-{{seq:04d}}',     'monthly', '盘点单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'transfer',        'TR{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '调拨单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'receiving',       'RV{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '收货单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'inventory_io',    'IO{{yyyy}}{{MM}}{{dd}}-{{seq:04d}}', 'daily',   '出入库单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'quality_check',   'QC{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '质检单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'waste',           'WS{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '损耗单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'supplier_audit',  'SA{{yyyy}}{{MM}}-{{seq:03d}}',       'monthly', '供应商审计单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'member_topup',    'MT{{yyyy}}{{MM}}{{dd}}-{{seq:04d}}', 'daily',   '会员充值系统默认'),
            ('{SYSTEM_TENANT_ID}', 'order',           'ORD{{yyyy}}{{MM}}{{dd}}-{{seq:04d}}','daily',   '订单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'invoice',         'INV{{yyyy}}{{MM}}-{{seq:04d}}',      'monthly', '发票系统默认'),
            ('{SYSTEM_TENANT_ID}', 'wine_storage',    'WS{{yyyy}}{{MM}}-{{seq:04d}}',       'monthly', '存酒单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'refund',          'RF{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '退款单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'payment',         'PY{{yyyy}}{{MM}}{{dd}}-{{seq:04d}}', 'daily',   '支付单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'settlement',      'ST{{yyyy}}{{MM}}-{{seq:04d}}',       'monthly', '结算单系统默认'),
            ('{SYSTEM_TENANT_ID}', 'adjustment',      'AJ{{yyyy}}{{MM}}{{dd}}-{{seq:03d}}', 'daily',   '调整单系统默认')
        ON CONFLICT (tenant_id, doc_type) DO NOTHING
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "doc_number_sequences" in existing:
        op.execute("DROP TABLE doc_number_sequences CASCADE")
    if "doc_number_rules" in existing:
        op.execute("DROP TABLE doc_number_rules CASCADE")
