"""v090: 试点验证闭环 — 四张核心表

新建表：
  pilot_programs   — 试点计划（含成功标准定义）
  pilot_items      — 试点项目条目（一计划多条目）
  pilot_metrics    — 每日指标快照（试验组 vs 对照组）
  pilot_reviews    — 试点复盘报告（AI 生成）

设计要点：
  - pilot_metrics 按 (pilot_program_id, store_id, metric_date) 建唯一索引，支持 upsert
  - 全部表含 tenant_id，启用 RLS（v006+ 标准安全模式，禁止 NULL 绕过）
  - 来源情报 source_ref_id 关联 intel_report / competitor_watch 等情报主键

RLS：ENABLE + FORCE，4 种操作各建独立策略。

Revision ID: v090
Revises: v088
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v090"
down_revision = "v089"
branch_labels = None
depends_on = None

# v006+ 标准 RLS 条件（禁止 NULL 绕过）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(
            f"CREATE POLICY {table}_{action.lower()}_tenant "
            f"ON {table} FOR {action} USING ({_RLS_COND})"
        )


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # 1. pilot_programs — 试点计划
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pilot_programs (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,

            name                VARCHAR(200) NOT NULL,
            description         TEXT,

            pilot_type          VARCHAR(30)  NOT NULL
                CHECK (pilot_type IN (
                    'new_dish',
                    'new_ingredient',
                    'new_combo',
                    'price_change',
                    'menu_restructure'
                )),

            recommendation_source VARCHAR(30) NOT NULL DEFAULT 'manual'
                CHECK (recommendation_source IN (
                    'intel_report',
                    'competitor_watch',
                    'trend_signal',
                    'manual'
                )),

            source_ref_id       UUID,
            hypothesis          TEXT,

            target_stores       JSONB        NOT NULL DEFAULT '[]'::jsonb,
            control_stores      JSONB,

            start_date          DATE         NOT NULL,
            end_date            DATE         NOT NULL,

            status              VARCHAR(20)  NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'paused', 'completed', 'cancelled')),

            success_criteria    JSONB        NOT NULL DEFAULT '[]'::jsonb,

            created_by          UUID,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_programs_tenant ON pilot_programs(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_programs_status ON pilot_programs(tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_programs_type ON pilot_programs(tenant_id, pilot_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_programs_dates ON pilot_programs(start_date, end_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_programs_source_ref ON pilot_programs(tenant_id, source_ref_id) WHERE source_ref_id IS NOT NULL")

    _enable_rls("pilot_programs")

    # ──────────────────────────────────────────────────────────────────
    # 2. pilot_items — 试点项目条目
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pilot_items (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            pilot_program_id    UUID         NOT NULL,

            item_type           VARCHAR(20)  NOT NULL
                CHECK (item_type IN ('dish', 'ingredient', 'price')),

            item_ref_id         UUID,
            item_name           VARCHAR(200) NOT NULL,

            action              VARCHAR(20)  NOT NULL
                CHECK (action IN ('add', 'remove', 'modify', 'price_change')),

            action_config       JSONB        NOT NULL DEFAULT '{}'::jsonb,
            is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_items_program ON pilot_items(tenant_id, pilot_program_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_items_ref ON pilot_items(tenant_id, item_ref_id) WHERE item_ref_id IS NOT NULL")

    _enable_rls("pilot_items")

    # ──────────────────────────────────────────────────────────────────
    # 3. pilot_metrics — 每日指标快照
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pilot_metrics (
            id                          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID         NOT NULL,
            pilot_program_id            UUID         NOT NULL,
            store_id                    UUID         NOT NULL,
            is_control_store            BOOLEAN      NOT NULL DEFAULT FALSE,

            metric_date                 DATE         NOT NULL,

            dish_sales_count            INTEGER      NOT NULL DEFAULT 0,
            dish_revenue                NUMERIC(14,2) NOT NULL DEFAULT 0,
            avg_order_value             NUMERIC(14,2),
            customer_satisfaction_score NUMERIC(5,2),
            repeat_purchase_rate        NUMERIC(5,4),

            raw_metrics                 JSONB        NOT NULL DEFAULT '{}'::jsonb,

            created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # 唯一约束：同一门店同一试点同一日期只能有一行，支持 upsert
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pilot_metrics_program_store_date
        ON pilot_metrics(pilot_program_id, store_id, metric_date)
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_metrics_tenant ON pilot_metrics(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_metrics_program ON pilot_metrics(tenant_id, pilot_program_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_metrics_store ON pilot_metrics(tenant_id, store_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_metrics_date ON pilot_metrics(pilot_program_id, metric_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_metrics_control ON pilot_metrics(pilot_program_id, is_control_store, metric_date)")

    _enable_rls("pilot_metrics")

    # ──────────────────────────────────────────────────────────────────
    # 4. pilot_reviews — 试点复盘报告
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pilot_reviews (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            pilot_program_id    UUID         NOT NULL,

            review_type         VARCHAR(20)  NOT NULL DEFAULT 'interim'
                CHECK (review_type IN ('interim', 'final')),

            overall_verdict     VARCHAR(30)  NOT NULL
                CHECK (overall_verdict IN ('success', 'partial_success', 'failed', 'inconclusive')),

            key_findings        JSONB        NOT NULL DEFAULT '[]'::jsonb,
            recommendations     JSONB        NOT NULL DEFAULT '[]'::jsonb,
            metrics_summary     JSONB        NOT NULL DEFAULT '{}'::jsonb,
            ai_analysis         TEXT,

            reviewed_by         UUID,
            reviewed_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_reviews_program ON pilot_reviews(tenant_id, pilot_program_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_reviews_verdict ON pilot_reviews(tenant_id, overall_verdict)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pilot_reviews_type ON pilot_reviews(pilot_program_id, review_type)")

    _enable_rls("pilot_reviews")


def downgrade() -> None:
    for table in ("pilot_reviews", "pilot_metrics", "pilot_items", "pilot_programs"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
