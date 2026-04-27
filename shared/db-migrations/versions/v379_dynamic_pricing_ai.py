"""Sprint D3c: AI动态定价引擎 — 2张新表

表1 dynamic_pricing_rules: 动态定价规则（时段/需求/库存/天气/会员等级维度）
表2 dynamic_pricing_logs: 动态定价执行日志（每次调价留痕+上下文快照）

所有表启用 RLS + FORCE ROW LEVEL SECURITY。

Revision ID: v379_dynamic_pricing_ai
Revises: v378_daily_scorecard
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v379_dynamic_pricing_ai"
down_revision: Union[str, None] = "v378_daily_scorecard"
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
    # ─────────────────────────────────────────────────────────────────
    # 1. dynamic_pricing_rules — 动态定价规则
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_pricing_rules (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL,
            store_id          UUID NOT NULL,
            dish_id           UUID NOT NULL,

            rule_type         VARCHAR(20) NOT NULL
                              CHECK (rule_type IN (
                                  'time_based', 'demand_based',
                                  'inventory_based', 'weather_based',
                                  'member_tier'
                              )),
            daypart           VARCHAR(20)
                              CHECK (daypart IS NULL OR daypart IN (
                                  'lunch', 'afternoon', 'dinner', 'late'
                              )),
            condition         JSONB NOT NULL DEFAULT '{}',
            adjustment_type   VARCHAR(10) NOT NULL
                              CHECK (adjustment_type IN ('percent', 'fixed')),
            adjustment_value  INT NOT NULL,
            min_price_fen     INT,
            max_price_fen     INT,
            priority          SMALLINT NOT NULL DEFAULT 0,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from    DATE,
            effective_until   DATE,

            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_dynamic_pricing_rule
                UNIQUE (tenant_id, store_id, dish_id, rule_type, daypart)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dpr_store_dish
        ON dynamic_pricing_rules (store_id, dish_id)
        WHERE is_deleted = false AND is_active = true
    """)

    _enable_rls("dynamic_pricing_rules")

    # ─────────────────────────────────────────────────────────────────
    # 2. dynamic_pricing_logs — 动态定价执行日志
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dynamic_pricing_logs (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL,
            store_id          UUID NOT NULL,
            dish_id           UUID NOT NULL,
            pricing_date      DATE NOT NULL,

            original_price_fen  INT NOT NULL,
            adjusted_price_fen  INT NOT NULL,
            adjustment_reason   TEXT,
            rules_applied       JSONB NOT NULL DEFAULT '[]',
            context             JSONB NOT NULL DEFAULT '{}',

            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dpl_dish_date
        ON dynamic_pricing_logs (store_id, dish_id, pricing_date)
        WHERE is_deleted = false
    """)

    _enable_rls("dynamic_pricing_logs")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dynamic_pricing_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS dynamic_pricing_rules CASCADE")
