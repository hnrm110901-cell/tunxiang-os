"""v100: 分账引擎 — 支付通道分账 + 品牌/加盟分润规则

新建 2 张表：
  profit_split_rules   — 分润规则配置（recipient_type/percentage/fixed/适用范围）
  profit_split_records — 每笔交易分润流水（按规则匹配后生成）

设计要点：
  - split_method 支持 percentage（按比例）和 fixed_fen（固定金额）两种
  - applicable_stores/applicable_channels 为 JSONB 数组，空数组 = 全适用
  - priority 控制多规则同时匹配时的执行顺序（数字越小越先执行）
  - valid_from/valid_to 支持有效期控制（新店开业期让利、节假日政策等）
  - profit_split_records.status: pending → settled / cancelled

Revision ID: v100
Revises: v099
Create Date: 2026-04-01
"""

from alembic import op

revision = "v100"
down_revision = "v099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. profit_split_rules — 分润规则 ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS profit_split_rules (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            name             VARCHAR(100) NOT NULL,
            recipient_type   VARCHAR(30)  NOT NULL,
            recipient_id     UUID,
            split_method     VARCHAR(20)  NOT NULL CHECK (split_method IN ('percentage','fixed_fen')),
            percentage       NUMERIC(7,6),
            fixed_fen        INT,
            applicable_stores   JSONB     NOT NULL DEFAULT '[]',
            applicable_channels JSONB     NOT NULL DEFAULT '[]',
            priority         INT          NOT NULL DEFAULT 0,
            is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
            valid_from       DATE,
            valid_to         DATE,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT split_rule_method_check CHECK (
                (split_method = 'percentage' AND percentage IS NOT NULL) OR
                (split_method = 'fixed_fen'  AND fixed_fen IS NOT NULL)
            )
        )
    """)
    op.execute("ALTER TABLE profit_split_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY profit_split_rules_rls ON profit_split_rules
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_rules_tenant_active
            ON profit_split_rules(tenant_id, is_active, priority)
            WHERE is_active = TRUE
    """)

    # ── 2. profit_split_records — 分润流水 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS profit_split_records (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            order_id         UUID        NOT NULL,
            store_id         UUID        NOT NULL,
            channel          VARCHAR(30),
            rule_id          UUID        NOT NULL REFERENCES profit_split_rules(id),
            recipient_type   VARCHAR(30) NOT NULL,
            recipient_id     UUID,
            gross_amount_fen INT         NOT NULL,
            split_amount_fen INT         NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            settled_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE profit_split_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY profit_split_records_rls ON profit_split_records
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_records_order
            ON profit_split_records(tenant_id, order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_records_recipient
            ON profit_split_records(tenant_id, recipient_type, recipient_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_split_records_store_date
            ON profit_split_records(tenant_id, store_id, created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS profit_split_records CASCADE")
    op.execute("DROP TABLE IF EXISTS profit_split_rules CASCADE")
