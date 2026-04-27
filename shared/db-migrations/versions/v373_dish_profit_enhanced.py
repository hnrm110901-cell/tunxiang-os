"""菜品利润图谱增强 — 定价建议 + 菜品共现分析

新增 2 张表：
  dish_pricing_suggestions — 基于BCG四象限的智能定价建议（raise/lower/delist/bundle/promote）
  dish_co_occurrence       — 菜品共现关联图谱（Jaccard相似度，用于下架影响评估）

RLS：使用 v064+ 标准（NULLIF + FORCE ROW LEVEL SECURITY）

Revision ID: v373_dish_profit_enhanced
Revises: v372_ceo_cockpit
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v373_dish_profit_enhanced"
down_revision: Union[str, None] = "v372_ceo_cockpit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_TABLES = [
    "dish_pricing_suggestions",
    "dish_co_occurrence",
]


def _apply_safe_rls(table: str) -> None:
    """4 操作 PERMISSIVE + NULLIF NULL-guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("SELECT", f"FOR SELECT USING ({_SAFE_CONDITION})"),
        ("INSERT", f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"),
        ("UPDATE", f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"),
        ("DELETE", f"FOR DELETE USING ({_SAFE_CONDITION})"),
    ]:
        suffix = action.lower()
        op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.execute(f"CREATE POLICY {table}_rls_{suffix} ON {table} {clause}")


def _create_updated_at_trigger(table: str) -> None:
    """为指定表创建 updated_at 自动维护 trigger。"""
    op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION fn_set_updated_at_v372();
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 0. 公共 trigger 函数
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_set_updated_at_v372()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ─────────────────────────────────────────────────────────────────
    # 1. dish_pricing_suggestions — 菜品定价建议表
    #    suggestion_type: raise/lower/delist/bundle/promote
    #    bcg_quadrant: star/cash_cow/question_mark/dog
    #    status: pending/accepted/rejected/applied
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_pricing_suggestions (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL,
            store_id              UUID         NOT NULL,
            dish_id               UUID         NOT NULL,
            suggestion_date       DATE         NOT NULL,
            current_price_fen     INT          NOT NULL,
            suggested_price_fen   INT,
            suggestion_type       VARCHAR(20)  NOT NULL
                                        CHECK (suggestion_type IN
                                        ('raise','lower','delist','bundle','promote')),
            bcg_quadrant          VARCHAR(20)
                                        CHECK (bcg_quadrant IS NULL OR bcg_quadrant IN
                                        ('star','cash_cow','question_mark','dog')),
            reason                TEXT         NOT NULL,
            estimated_impact_fen  INT          DEFAULT 0,
            status                VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                        CHECK (status IN
                                        ('pending','accepted','rejected','applied')),
            applied_at            TIMESTAMPTZ,
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted            BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dps_tenant_store_date "
        "ON dish_pricing_suggestions (tenant_id, store_id, suggestion_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dps_tenant_dish "
        "ON dish_pricing_suggestions (tenant_id, dish_id, suggestion_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dps_tenant_status "
        "ON dish_pricing_suggestions (tenant_id, status) "
        "WHERE is_deleted = FALSE AND status = 'pending'"
    )
    _create_updated_at_trigger("dish_pricing_suggestions")
    _apply_safe_rls("dish_pricing_suggestions")

    # ─────────────────────────────────────────────────────────────────
    # 2. dish_co_occurrence — 菜品关联图谱（共现分析）
    #    correlation_score: Jaccard相似度 0~1
    #    UNIQUE 约束保证同一时间段内菜品对唯一
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_co_occurrence (
            id                    UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID           NOT NULL,
            store_id              UUID           NOT NULL,
            dish_a_id             UUID           NOT NULL,
            dish_b_id             UUID           NOT NULL,
            co_occurrence_count   INT            NOT NULL DEFAULT 0,
            correlation_score     NUMERIC(5, 4)  NOT NULL DEFAULT 0,
            period_start          DATE           NOT NULL,
            period_end            DATE           NOT NULL,
            created_at            TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            is_deleted            BOOLEAN        NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_co_occurrence_pair UNIQUE (
                tenant_id, store_id, dish_a_id, dish_b_id, period_start
            ),
            CONSTRAINT ck_co_occurrence_dish_order CHECK (dish_a_id < dish_b_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dco_tenant_store_period "
        "ON dish_co_occurrence (tenant_id, store_id, period_start DESC) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dco_tenant_dish_a "
        "ON dish_co_occurrence (tenant_id, dish_a_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dco_tenant_dish_b "
        "ON dish_co_occurrence (tenant_id, dish_b_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dco_correlation "
        "ON dish_co_occurrence (tenant_id, store_id, correlation_score DESC) "
        "WHERE is_deleted = FALSE AND correlation_score > 0.3"
    )
    _create_updated_at_trigger("dish_co_occurrence")
    _apply_safe_rls("dish_co_occurrence")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table};")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    op.execute("DROP FUNCTION IF EXISTS fn_set_updated_at_v372();")
