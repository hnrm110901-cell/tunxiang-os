"""最低消费/服务费规则引擎 — billing_rules 表

模块1.4（对标天财商龙）：门店级账单规则，支持最低消费 + 服务费两种规则类型。

Tables: billing_rules
Sprint: P0-S4 账单规则引擎

Revision ID: v238
Revises: v237
Create Date: 2026-04-12
"""

from alembic import op

revision = "v238"
down_revision = "v237b"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_rules (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            rule_type               VARCHAR(20) NOT NULL,
            calc_method             VARCHAR(30) NOT NULL DEFAULT 'fixed',
            threshold_fen           BIGINT      NOT NULL DEFAULT 0,
            service_fee_rate        NUMERIC(6,4) NOT NULL DEFAULT 0,
            exempt_member_tiers     JSONB       NOT NULL DEFAULT '[]',
            exempt_agreement_units  JSONB       NOT NULL DEFAULT '[]',
            is_active               BOOLEAN     NOT NULL DEFAULT true,
            created_at              TIMESTAMPTZ DEFAULT now(),
            updated_at              TIMESTAMPTZ DEFAULT now(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT false,

            CONSTRAINT billing_rules_rule_type_check
                CHECK (rule_type IN ('min_spend', 'service_fee')),
            CONSTRAINT billing_rules_calc_method_check
                CHECK (calc_method IN ('fixed', 'per_person', 'percentage')),
            CONSTRAINT billing_rules_threshold_fen_check
                CHECK (threshold_fen >= 0),
            CONSTRAINT billing_rules_service_fee_rate_check
                CHECK (service_fee_rate >= 0 AND service_fee_rate <= 1)
        );

        COMMENT ON TABLE billing_rules IS
            '账单规则表：每门店可配置多条规则（最低消费 min_spend / 服务费 service_fee），对标天财商龙模块1.4';

        COMMENT ON COLUMN billing_rules.rule_type IS
            '规则类型：min_spend=最低消费 / service_fee=服务费';
        COMMENT ON COLUMN billing_rules.calc_method IS
            '计算方式：fixed=固定金额 / per_person=按人头 / percentage=按消费比例（仅service_fee）';
        COMMENT ON COLUMN billing_rules.threshold_fen IS
            '阈值金额，单位：分(fen)。min_spend时为最低消费金额；per_person时为人均最低消费；service_fee/fixed时为固定服务费金额';
        COMMENT ON COLUMN billing_rules.service_fee_rate IS
            '服务费费率（0~1），仅 calc_method=percentage 时有效。例：0.1 = 10%服务费';
        COMMENT ON COLUMN billing_rules.exempt_member_tiers IS
            '豁免会员等级列表（JSONB数组），例：["gold","platinum"]，这些等级的会员免服务费/最低消费';
        COMMENT ON COLUMN billing_rules.exempt_agreement_units IS
            '豁免协议单位列表（JSONB数组），例：["unit_abc_corp"]，这些协议单位免服务费';

        CREATE INDEX IF NOT EXISTS ix_billing_rules_tenant_store_active
            ON billing_rules (tenant_id, store_id, is_active)
            WHERE is_deleted = false;

        CREATE INDEX IF NOT EXISTS ix_billing_rules_tenant_store_type
            ON billing_rules (tenant_id, store_id, rule_type)
            WHERE is_deleted = false;
    """)

    # ── RLS Policy ──────────────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE billing_rules ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS billing_rules_tenant_isolation ON billing_rules;
        CREATE POLICY billing_rules_tenant_isolation ON billing_rules
            USING ({cond});
    """.format(cond=_RLS_COND)
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS billing_rules CASCADE;")
