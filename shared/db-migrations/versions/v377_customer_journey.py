"""Sprint G4: 顾客体验链路监控 — 3张新表

表1 customer_journey_timings: 顾客全旅程时间打点（到店→入座→点单→上菜→结账→离店）
表2 satisfaction_ratings: 满意度评分（整体/食物/服务/速度 + NPS）
表3 conversion_funnel_daily: 每日转化漏斗（曝光→到店→消费→会员→复购）

所有表启用 RLS + FORCE ROW LEVEL SECURITY。
GENERATED ALWAYS AS 列由 PostgreSQL 自动计算，无需 INSERT/UPDATE。

Revision ID: v377_customer_journey
Revises: v376_ceo_cockpit
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v377_customer_journey"
down_revision: Union[str, None] = "v376_ceo_cockpit"
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
    # 1. customer_journey_timings
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_journey_timings (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            order_id        UUID,
            table_id        UUID,
            journey_date    DATE NOT NULL,

            arrived_at      TIMESTAMPTZ,
            seated_at       TIMESTAMPTZ,
            ordered_at      TIMESTAMPTZ,
            first_served_at TIMESTAMPTZ,
            paid_at         TIMESTAMPTZ,
            left_at         TIMESTAMPTZ,

            wait_minutes    NUMERIC(6,1) GENERATED ALWAYS AS (
                EXTRACT(EPOCH FROM (seated_at - arrived_at)) / 60
            ) STORED,
            order_minutes   NUMERIC(6,1) GENERATED ALWAYS AS (
                EXTRACT(EPOCH FROM (ordered_at - seated_at)) / 60
            ) STORED,
            serve_minutes   NUMERIC(6,1) GENERATED ALWAYS AS (
                EXTRACT(EPOCH FROM (first_served_at - ordered_at)) / 60
            ) STORED,
            dine_minutes    NUMERIC(6,1) GENERATED ALWAYS AS (
                EXTRACT(EPOCH FROM (paid_at - first_served_at)) / 60
            ) STORED,
            total_minutes   NUMERIC(6,1) GENERATED ALWAYS AS (
                EXTRACT(EPOCH FROM (COALESCE(left_at, paid_at) - arrived_at)) / 60
            ) STORED,

            party_size      SMALLINT,
            is_delivery     BOOLEAN NOT NULL DEFAULT FALSE,

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cjt_tenant_store_date "
        "ON customer_journey_timings (tenant_id, store_id, journey_date) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cjt_order "
        "ON customer_journey_timings (order_id) "
        "WHERE order_id IS NOT NULL AND is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cjt_active "
        "ON customer_journey_timings (tenant_id, store_id) "
        "WHERE paid_at IS NULL AND arrived_at IS NOT NULL AND is_deleted = FALSE"
    )

    _enable_rls("customer_journey_timings")

    # ─────────────────────────────────────────────────────────────────
    # 2. satisfaction_ratings
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS satisfaction_ratings (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            order_id        UUID,
            journey_id      UUID REFERENCES customer_journey_timings(id),

            overall_score   SMALLINT NOT NULL CHECK (overall_score >= 1 AND overall_score <= 5),
            food_score      SMALLINT CHECK (food_score >= 1 AND food_score <= 5),
            service_score   SMALLINT CHECK (service_score >= 1 AND service_score <= 5),
            speed_score     SMALLINT CHECK (speed_score >= 1 AND speed_score <= 5),
            comment         TEXT,
            source          VARCHAR(20) NOT NULL DEFAULT 'miniapp',

            is_negative     BOOLEAN GENERATED ALWAYS AS (overall_score <= 2) STORED,

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sr_tenant_store "
        "ON satisfaction_ratings (tenant_id, store_id, created_at DESC) "
        "WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sr_negative "
        "ON satisfaction_ratings (tenant_id, store_id, created_at DESC) "
        "WHERE is_negative = TRUE AND is_deleted = FALSE"
    )

    _enable_rls("satisfaction_ratings")

    # ─────────────────────────────────────────────────────────────────
    # 3. conversion_funnel_daily
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversion_funnel_daily (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            funnel_date     DATE NOT NULL,

            exposure_count  INT NOT NULL DEFAULT 0,
            visit_count     INT NOT NULL DEFAULT 0,
            order_count     INT NOT NULL DEFAULT 0,
            member_count    INT NOT NULL DEFAULT 0,
            repeat_count    INT NOT NULL DEFAULT 0,

            visit_rate      NUMERIC(5,2) GENERATED ALWAYS AS (
                CASE WHEN exposure_count > 0
                     THEN visit_count * 100.0 / exposure_count
                     ELSE 0
                END
            ) STORED,
            order_rate      NUMERIC(5,2) GENERATED ALWAYS AS (
                CASE WHEN visit_count > 0
                     THEN order_count * 100.0 / visit_count
                     ELSE 0
                END
            ) STORED,
            member_rate     NUMERIC(5,2) GENERATED ALWAYS AS (
                CASE WHEN order_count > 0
                     THEN member_count * 100.0 / order_count
                     ELSE 0
                END
            ) STORED,
            repeat_rate     NUMERIC(5,2) GENERATED ALWAYS AS (
                CASE WHEN member_count > 0
                     THEN repeat_count * 100.0 / member_count
                     ELSE 0
                END
            ) STORED,

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_funnel_tenant_store_date
                UNIQUE (tenant_id, store_id, funnel_date)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cfd_tenant_store_date "
        "ON conversion_funnel_daily (tenant_id, store_id, funnel_date DESC) "
        "WHERE is_deleted = FALSE"
    )

    _enable_rls("conversion_funnel_daily")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversion_funnel_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS satisfaction_ratings CASCADE")
    op.execute("DROP TABLE IF EXISTS customer_journey_timings CASCADE")
