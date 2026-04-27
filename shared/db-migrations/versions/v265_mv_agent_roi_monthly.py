"""v265 — mv_agent_roi_monthly 物化视图（Sprint D2）

按租户+门店+Agent+月份聚合 ROI 指标，供 tx-agent 的 `/api/v1/agent/roi/*` 接口
和 Grafana 看板直读，避免每次遍历全量 agent_decision_logs。

视图聚合维度：
  period_month (DATE_TRUNC month) × tenant_id × store_id × agent_id

聚合指标（求和）：
  saved_labor_hours_sum         NUMERIC
  prevented_loss_fen_sum        BIGINT
  revenue_uplift_fen_sum        BIGINT  (从 improved_kpi->>'revenue_uplift_fen')
  nps_delta_avg                 NUMERIC (从 improved_kpi->>'nps_delta')
  decision_count                BIGINT
  avg_confidence                NUMERIC

刷新策略：
  - `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_agent_roi_monthly` 支持并发查询
  - 建议 cron 每日 02:00 刷新前 13 个月数据
  - 手工触发：`SELECT refresh_mv_agent_roi_monthly();`

Revision ID: v265_mv_roi
Revises: v264_roi
Create Date: 2026-04-23
"""
from alembic import op

revision = "v265_mv_roi"
down_revision = "v264_roi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 创建物化视图
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_agent_roi_monthly AS
        SELECT
            tenant_id,
            store_id,
            agent_id,
            DATE_TRUNC('month', decided_at)::date                AS period_month,
            COUNT(*)                                             AS decision_count,
            AVG(confidence)                                      AS avg_confidence,
            COALESCE(SUM(saved_labor_hours), 0)::numeric(14,2)   AS saved_labor_hours_sum,
            COALESCE(SUM(prevented_loss_fen), 0)::bigint         AS prevented_loss_fen_sum,
            COALESCE(
                SUM((improved_kpi->>'revenue_uplift_fen')::bigint),
                0
            )::bigint                                            AS revenue_uplift_fen_sum,
            AVG(
                NULLIF((improved_kpi->>'nps_delta')::numeric, NULL)
            )::numeric(6,2)                                      AS nps_delta_avg,
            MIN(decided_at)                                      AS first_decision_at,
            MAX(decided_at)                                      AS last_decision_at
        FROM agent_decision_logs
        WHERE is_deleted = false
          AND decided_at >= CURRENT_DATE - INTERVAL '13 months'
        GROUP BY
            tenant_id,
            store_id,
            agent_id,
            DATE_TRUNC('month', decided_at)
    """)

    # 2. UNIQUE 索引（CONCURRENTLY REFRESH 要求至少一个 unique index）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_agent_roi_monthly
            ON mv_agent_roi_monthly (
                tenant_id,
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid),
                agent_id,
                period_month
            )
    """)

    # 3. 常用查询索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_agent_roi_monthly_tenant_month
            ON mv_agent_roi_monthly (tenant_id, period_month DESC);
        CREATE INDEX IF NOT EXISTS idx_mv_agent_roi_monthly_agent
            ON mv_agent_roi_monthly (agent_id, period_month DESC);
    """)

    # 4. 刷新函数（便于应用层调用 SELECT refresh_mv_agent_roi_monthly();）
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_mv_agent_roi_monthly()
        RETURNS void AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY mv_agent_roi_monthly;
        EXCEPTION WHEN OTHERS THEN
            -- 首次刷新（还没 unique index 数据）走非并发刷新
            REFRESH MATERIALIZED VIEW mv_agent_roi_monthly;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 5. 视图注释
    op.execute("""
        COMMENT ON MATERIALIZED VIEW mv_agent_roi_monthly IS
            'Sprint D2: 按 tenant/store/agent/月份 聚合 ROI 指标，供驾驶舱读。每日 02:00 cron 刷新。';
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS refresh_mv_agent_roi_monthly()")
    op.execute("DROP INDEX IF EXISTS idx_mv_agent_roi_monthly_agent")
    op.execute("DROP INDEX IF EXISTS idx_mv_agent_roi_monthly_tenant_month")
    op.execute("DROP INDEX IF EXISTS ux_mv_agent_roi_monthly")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_agent_roi_monthly")
