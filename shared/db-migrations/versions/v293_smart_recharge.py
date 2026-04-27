"""v293 — 智能储值

4张新表：
  - smart_recharge_rules           — 智能储值规则（客单价倍数档位）
  - smart_recharge_recommendations — 储值推荐记录（推荐/接受/拒绝/过期）
  - recharge_performance           — 储值绩效（员工×日期×周期）
  - recharge_commission_rules      — 储值提成规则（固定/百分比/阶梯）

所有表启用 RLS 租户隔离。

Revision ID: v293
Revises: v292
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v293"
down_revision: Union[str, None] = "v292"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── smart_recharge_rules ──
    op.execute("""
    CREATE TABLE smart_recharge_rules (
        tenant_id           UUID          NOT NULL,
        id                  UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id            UUID,
        brand_id            UUID,
        rule_name           VARCHAR(100),
        is_active           BOOLEAN       DEFAULT TRUE,
        multiplier_tiers    JSONB         NOT NULL,
        min_recharge_fen    BIGINT        DEFAULT 0,
        max_recharge_fen    BIGINT        DEFAULT 999900,
        bonus_type          VARCHAR(20)   CHECK (bonus_type IN ('percentage', 'fixed', 'coupon')),
        bonus_value         NUMERIC(10,2) DEFAULT 0,
        coupon_template_id  UUID,
        effective_from      DATE          NOT NULL,
        effective_until     DATE,
        priority            INTEGER       DEFAULT 0,
        created_at          TIMESTAMPTZ   DEFAULT now(),
        updated_at          TIMESTAMPTZ   DEFAULT now(),
        is_deleted          BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE smart_recharge_rules ENABLE ROW LEVEL SECURITY;
    CREATE POLICY smart_recharge_rules_tenant ON smart_recharge_rules
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_smart_recharge_rules_tenant_store
        ON smart_recharge_rules (tenant_id, store_id);
    CREATE INDEX ix_smart_recharge_rules_brand
        ON smart_recharge_rules (tenant_id, brand_id);
    """)

    # ── smart_recharge_recommendations ──
    op.execute("""
    CREATE TABLE smart_recharge_recommendations (
        tenant_id           UUID          NOT NULL,
        id                  UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id            UUID          NOT NULL,
        customer_id         UUID,
        order_id            UUID          NOT NULL,
        order_amount_fen    BIGINT        NOT NULL,
        recommended_tiers   JSONB         NOT NULL,
        selected_tier       JSONB,
        recharge_amount_fen BIGINT,
        bonus_amount_fen    BIGINT,
        status              VARCHAR(20)   CHECK (status IN ('recommended', 'accepted', 'declined', 'expired'))
                                          DEFAULT 'recommended',
        recommended_at      TIMESTAMPTZ   DEFAULT now(),
        decided_at          TIMESTAMPTZ,
        employee_id         UUID,
        created_at          TIMESTAMPTZ   DEFAULT now(),
        updated_at          TIMESTAMPTZ   DEFAULT now(),
        is_deleted          BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE smart_recharge_recommendations ENABLE ROW LEVEL SECURITY;
    CREATE POLICY smart_recharge_recommendations_tenant ON smart_recharge_recommendations
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_smart_recharge_recs_tenant_store
        ON smart_recharge_recommendations (tenant_id, store_id);
    CREATE INDEX ix_smart_recharge_recs_order
        ON smart_recharge_recommendations (order_id);
    CREATE INDEX ix_smart_recharge_recs_customer
        ON smart_recharge_recommendations (tenant_id, customer_id);
    CREATE INDEX ix_smart_recharge_recs_status
        ON smart_recharge_recommendations (status);
    """)

    # ── recharge_performance ──
    op.execute("""
    CREATE TABLE recharge_performance (
        tenant_id                  UUID          NOT NULL,
        id                         UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id                   UUID          NOT NULL,
        employee_id                UUID          NOT NULL,
        period_date                DATE          NOT NULL,
        period_type                VARCHAR(10)   CHECK (period_type IN ('daily', 'monthly')),
        total_recharge_count       INTEGER       DEFAULT 0,
        total_recharge_amount_fen  BIGINT        DEFAULT 0,
        total_bonus_amount_fen     BIGINT        DEFAULT 0,
        smart_recharge_count       INTEGER       DEFAULT 0,
        smart_recharge_amount_fen  BIGINT        DEFAULT 0,
        conversion_rate            NUMERIC(5,2)  DEFAULT 0,
        commission_fen             BIGINT        DEFAULT 0,
        created_at                 TIMESTAMPTZ   DEFAULT now(),
        updated_at                 TIMESTAMPTZ   DEFAULT now(),
        is_deleted                 BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE recharge_performance ENABLE ROW LEVEL SECURITY;
    CREATE POLICY recharge_performance_tenant ON recharge_performance
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE UNIQUE INDEX ux_recharge_performance_key
        ON recharge_performance (tenant_id, store_id, employee_id, period_date, period_type);
    CREATE INDEX ix_recharge_performance_tenant_store_date
        ON recharge_performance (tenant_id, store_id, period_date);
    """)

    # ── recharge_commission_rules ──
    op.execute("""
    CREATE TABLE recharge_commission_rules (
        tenant_id        UUID          NOT NULL,
        id               UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id         UUID,
        rule_name        VARCHAR(100),
        commission_type  VARCHAR(20)   CHECK (commission_type IN ('flat_per_card', 'percentage', 'tiered')),
        commission_value NUMERIC(10,4) DEFAULT 0,
        tiers            JSONB,
        is_active        BOOLEAN       DEFAULT TRUE,
        effective_from   DATE          NOT NULL,
        effective_until  DATE,
        created_at       TIMESTAMPTZ   DEFAULT now(),
        updated_at       TIMESTAMPTZ   DEFAULT now(),
        is_deleted       BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE recharge_commission_rules ENABLE ROW LEVEL SECURITY;
    CREATE POLICY recharge_commission_rules_tenant ON recharge_commission_rules
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_recharge_commission_rules_tenant_store
        ON recharge_commission_rules (tenant_id, store_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recharge_commission_rules CASCADE;")
    op.execute("DROP TABLE IF EXISTS recharge_performance CASCADE;")
    op.execute("DROP TABLE IF EXISTS smart_recharge_recommendations CASCADE;")
    op.execute("DROP TABLE IF EXISTS smart_recharge_rules CASCADE;")
