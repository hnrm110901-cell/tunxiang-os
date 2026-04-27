"""Sprint G5: 角色KPI日得分卡 + 绩效奖金 + 门店生命周期 — 3张新表

表1 daily_scorecards: 员工日KPI得分卡（角色差异化维度+加权总分+排名+IM推送）
表2 bonus_rules: 绩效奖金规则（岗位基数×阶梯系数）
表3 store_lifecycle_stages: 门店生命周期阶段（爬坡/成熟/平台/衰退+差异化基准线）

所有表启用 RLS + FORCE ROW LEVEL SECURITY。
GENERATED ALWAYS AS 列由 PostgreSQL 自动计算。

Revision ID: v378_daily_scorecard
Revises: v377_customer_journey
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v378_daily_scorecard"
down_revision: Union[str, None] = "v377_customer_journey"
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
    # 1. daily_scorecards — 员工日KPI得分卡
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS daily_scorecards (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            employee_id             UUID NOT NULL,
            employee_name           VARCHAR(100),
            role                    VARCHAR(30) NOT NULL,

            score_date              DATE NOT NULL,
            total_score             NUMERIC(5,1) NOT NULL,
            dimension_scores        JSONB NOT NULL DEFAULT '{}',

            rank_in_role            SMALLINT,
            rank_total              SMALLINT,
            total_employees_in_role SMALLINT,
            vs_yesterday            NUMERIC(5,1),

            highlights              TEXT[],
            improvements            TEXT[],

            pushed_at               TIMESTAMPTZ,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_scorecard_tenant_store_emp_date
                UNIQUE (tenant_id, store_id, employee_id, score_date)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dsc_tenant_store_date "
        "ON daily_scorecards (tenant_id, store_id, score_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dsc_employee_date "
        "ON daily_scorecards (tenant_id, employee_id, score_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dsc_role_date "
        "ON daily_scorecards (tenant_id, store_id, role, score_date DESC) "
        "WHERE is_deleted = FALSE"
    )

    _enable_rls("daily_scorecards")

    # ─────────────────────────────────────────────────────────────────
    # 2. bonus_rules — 绩效奖金规则
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS bonus_rules (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            role                VARCHAR(30) NOT NULL,

            base_amount_fen     INT NOT NULL,
            tier_config         JSONB NOT NULL DEFAULT '[]',

            effective_from      DATE,
            effective_until     DATE,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_br_tenant_role "
        "ON bonus_rules (tenant_id, role, is_active) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_br_tenant_store "
        "ON bonus_rules (tenant_id, store_id, role) "
        "WHERE is_deleted = FALSE AND is_active = TRUE"
    )

    _enable_rls("bonus_rules")

    # ─────────────────────────────────────────────────────────────────
    # 3. store_lifecycle_stages — 门店生命周期阶段
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_lifecycle_stages (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,

            opened_date             DATE NOT NULL,
            current_stage           VARCHAR(20) NOT NULL
                                        CHECK (current_stage IN ('rampup', 'mature', 'plateau', 'decline')),
            stage_entered_at        DATE NOT NULL,

            months_since_opening    INT GENERATED ALWAYS AS (
                (EXTRACT(YEAR FROM age(CURRENT_DATE, opened_date)) * 12
                 + EXTRACT(MONTH FROM age(CURRENT_DATE, opened_date)))::INT
            ) STORED,

            health_baseline         JSONB,
            next_review_date        DATE,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_lifecycle_tenant_store
                UNIQUE (tenant_id, store_id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sls_tenant_stage "
        "ON store_lifecycle_stages (tenant_id, current_stage) "
        "WHERE is_deleted = FALSE"
    )

    _enable_rls("store_lifecycle_stages")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_lifecycle_stages CASCADE")
    op.execute("DROP TABLE IF EXISTS bonus_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS daily_scorecards CASCADE")
