"""v431 — RFQ 询价单 5 表 schema + supplier_portal_messages UNIQUE 索引（PRD-04 sub-A / Phase 2 W9 / T2 infra）

业务背景：
  AI 推荐供应商是黑盒，采购总监无法向老板/审计交代为何选 A 不选 B。国企/上市公司客户
  采购合规要求"三家比价"。本 PR sub-A 落 RFQ 5 表 schema 基础设施（schema-only，
  service / route / UI 在 sub-B/C ship）。

  #613 supplier_portal_messages UNIQUE 索引同期闭环（cert_expiry_alerter._log_alert
  失败-after-INSERT 重复行风险防护）。

设计要点：
  1. rfqs — RFQ 主表（询价单头）
     - rfq_number: 走 PRD-03 doc_number 规则生成（与 receiving/transfer 同 fallback 模式）
     - status: draft / published / quoting / comparing / awarded / cancelled
     - initiator_id / deadline / created_by
  2. rfq_items — RFQ 明细行（一询价单可含多 SKU）
     - rfq_id FK + ingredient_id + qty_required + spec_notes
  3. rfq_invitees — 供应商邀请记录（一询价单邀多供应商）
     - rfq_id + supplier_id (UNIQUE 同询价单不重邀) + invited_at + responded_at
  4. rfq_quotes — 供应商报价（一邀请可多 SKU 报价）
     - rfq_id + supplier_id + ingredient_id + unit_price_fen (分) + valid_until
  5. rfq_awards — 中标记录（Tier 1 资金路径前置 — sub-B award 写入）
     - rfq_id (UNIQUE 单单只能一中标) + selected_quote_id + reason + approved_by
     - ai_recommendation_followed BOOLEAN  ⭐ RLHF 训练信号
  6. supplier_portal_messages 加 partial UNIQUE index (#613 闭环)
     - UNIQUE (tenant_id, supplier_id, message_type, (metadata->>'cert_id'),
       (metadata->>'threshold')) WHERE message_type='cert_expiry_alert'
     - cert_expiry_alerter._push_supplier_portal 同期加 ON CONFLICT DO NOTHING (本 PR 配套 commit)

RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
inline ALTER TABLE / CREATE POLICY 模式（与 v428/v429/v430 一致，让 RLS gate regex
扫描器可见 — 不可用 f-string helper，因 regex 不展开 Python 字面量）

Revision ID: v431_rfq_schema
Revises: v430_supplier_delivery_windows
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v431_rfq_schema"
down_revision: Union[str, Sequence[str], None] = "v430_supplier_delivery_windows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ───── rfqs 主表 ──────────────────────────────────────────────────────────
    if "rfqs" not in existing:
        op.execute(
            """
            CREATE TABLE rfqs (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                rfq_number          VARCHAR(64),
                initiator_id        UUID NOT NULL,
                deadline            TIMESTAMPTZ NOT NULL,
                status              VARCHAR(16) NOT NULL DEFAULT 'draft',
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_rfq_status
                    CHECK (status IN ('draft','published','quoting','comparing','awarded','cancelled'))
            )
            """
        )
        op.execute("ALTER TABLE rfqs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE rfqs FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY rfqs_tenant_isolation
            ON rfqs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_rfqs_tenant_status_deadline
            ON rfqs (tenant_id, status, deadline)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_rfqs_tenant_rfq_number
            ON rfqs (tenant_id, rfq_number)
            WHERE rfq_number IS NOT NULL AND is_deleted = FALSE
            """
        )

    # ───── rfq_items 明细 ─────────────────────────────────────────────────────
    if "rfq_items" not in existing:
        op.execute(
            """
            CREATE TABLE rfq_items (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                rfq_id              UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                qty_required        NUMERIC(14,4) NOT NULL,
                qty_unit            VARCHAR(16),
                spec_notes          TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_rfq_items_qty_positive
                    CHECK (qty_required > 0),
                CONSTRAINT fk_rfq_items_rfq
                    FOREIGN KEY (rfq_id) REFERENCES rfqs(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE rfq_items ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE rfq_items FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY rfq_items_tenant_isolation
            ON rfq_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_rfq_items_rfq
            ON rfq_items (tenant_id, rfq_id)
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_rfq_items_rfq_ingredient
            ON rfq_items (tenant_id, rfq_id, ingredient_id)
            """
        )

    # ───── rfq_invitees 邀请记录 ──────────────────────────────────────────────
    if "rfq_invitees" not in existing:
        op.execute(
            """
            CREATE TABLE rfq_invitees (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                rfq_id              UUID NOT NULL,
                supplier_id         UUID NOT NULL,
                invited_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                responded_at        TIMESTAMPTZ,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT fk_rfq_invitees_rfq
                    FOREIGN KEY (rfq_id) REFERENCES rfqs(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE rfq_invitees ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE rfq_invitees FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY rfq_invitees_tenant_isolation
            ON rfq_invitees
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_rfq_invitees_rfq_supplier
            ON rfq_invitees (tenant_id, rfq_id, supplier_id)
            """
        )
        op.execute(
            """
            CREATE INDEX idx_rfq_invitees_supplier_pending
            ON rfq_invitees (tenant_id, supplier_id, responded_at)
            """
        )

    # ───── rfq_quotes 供应商报价 ──────────────────────────────────────────────
    if "rfq_quotes" not in existing:
        op.execute(
            """
            CREATE TABLE rfq_quotes (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                rfq_id              UUID NOT NULL,
                supplier_id         UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                unit_price_fen      BIGINT NOT NULL,
                qty_offered         NUMERIC(14,4),
                valid_until         DATE,
                notes               TEXT,
                submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_rfq_quotes_price_positive
                    CHECK (unit_price_fen > 0),
                CONSTRAINT fk_rfq_quotes_rfq
                    FOREIGN KEY (rfq_id) REFERENCES rfqs(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE rfq_quotes ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE rfq_quotes FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY rfq_quotes_tenant_isolation
            ON rfq_quotes
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_rfq_quotes_rfq_supplier_ingredient
            ON rfq_quotes (tenant_id, rfq_id, supplier_id, ingredient_id)
            """
        )
        op.execute(
            """
            CREATE INDEX idx_rfq_quotes_rfq_ingredient_price
            ON rfq_quotes (tenant_id, rfq_id, ingredient_id, unit_price_fen)
            """
        )

    # ───── rfq_awards 中标记录（Tier 1 资金路径前置）──────────────────────────
    if "rfq_awards" not in existing:
        op.execute(
            """
            CREATE TABLE rfq_awards (
                id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id                   UUID NOT NULL,
                rfq_id                      UUID NOT NULL,
                selected_quote_id           UUID NOT NULL,
                reason                      TEXT NOT NULL,
                ai_recommendation_followed  BOOLEAN,
                approved_by                 UUID,
                approved_at                 TIMESTAMPTZ,
                created_by                  UUID NOT NULL,
                created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT fk_rfq_awards_rfq
                    FOREIGN KEY (rfq_id) REFERENCES rfqs(id) ON DELETE CASCADE,
                CONSTRAINT fk_rfq_awards_quote
                    FOREIGN KEY (selected_quote_id) REFERENCES rfq_quotes(id) ON DELETE RESTRICT
            )
            """
        )
        op.execute("ALTER TABLE rfq_awards ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE rfq_awards FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY rfq_awards_tenant_isolation
            ON rfq_awards
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_rfq_awards_rfq
            ON rfq_awards (tenant_id, rfq_id)
            """
        )
        op.execute(
            """
            CREATE INDEX idx_rfq_awards_quote
            ON rfq_awards (tenant_id, selected_quote_id)
            """
        )

    # ───── #613 supplier_portal_messages partial UNIQUE 索引（cert_alert 幂等）──
    # 同 cert_id + threshold + 供应商 + tenant + cert_expiry_alert 类型不允许重复入 inbox
    # cert_expiry_alerter._push_supplier_portal 同期加 ON CONFLICT DO NOTHING（本 PR 配套 commit）
    if "supplier_portal_messages" in existing:
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_portal_cert_alert
            ON supplier_portal_messages (
                tenant_id,
                supplier_id,
                message_type,
                (metadata->>'cert_id'),
                (metadata->>'threshold')
            )
            WHERE message_type = 'cert_expiry_alert'
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    op.execute("DROP INDEX IF EXISTS uq_supplier_portal_cert_alert")

    # FK 依赖序：awards → quotes → invitees → items → rfqs（先删子表）
    if "rfq_awards" in existing:
        op.execute("DROP TABLE rfq_awards CASCADE")
    if "rfq_quotes" in existing:
        op.execute("DROP TABLE rfq_quotes CASCADE")
    if "rfq_invitees" in existing:
        op.execute("DROP TABLE rfq_invitees CASCADE")
    if "rfq_items" in existing:
        op.execute("DROP TABLE rfq_items CASCADE")
    if "rfqs" in existing:
        op.execute("DROP TABLE rfqs CASCADE")
