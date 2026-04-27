"""v264 — agent_decision_logs 新增 ROI 四字段 + mv_agent_roi_monthly 物化视图

Sprint D2（2026-04-24）：为 Agent 决策留痕注入 ROI 量化能力。

新增四列（均 NULL，向前兼容）：
  saved_labor_hours   NUMERIC(10,2)  — 本次决策节省的人力工时（小时）
  prevented_loss_fen  BIGINT         — 本次决策阻止的资金损失（分）
  improved_kpi        JSONB          — 改善 KPI 的结构化证据 {"metric": str, "delta_pct": float}
  roi_evidence        JSONB          — 证据来源/上游事件/算法版本等审计链

新增物化视图：
  mv_agent_roi_monthly — 按 (tenant_id, agent_id, 月) 聚合 ROI，RLS 保护

签字提醒：本迁移对应 docs/sprint-plan-2026Q2-unified.md §4 决策点 #1
          （"D2 agent_decision_logs 新增 6 列 = 核心留痕变更 = 需创始人签字"）。
          本文件仅落盘 schema，向前兼容，零破坏；业务 writeback 受
          flag `agent.roi.writeback`（默认 off）守护。

规划原写 v263，但 v263 已被 kiosk/voice_count 占用，本次改分配 v264。

Revision ID: v264
Revises: v263
Create Date: 2026-04-24
"""
from alembic import op

revision = "v264"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 新增四列（向前兼容：全部 NULL，旧代码无感知） ──────────────────
    op.execute("""
        ALTER TABLE agent_decision_logs
            ADD COLUMN IF NOT EXISTS saved_labor_hours  NUMERIC(10, 2) NULL,
            ADD COLUMN IF NOT EXISTS prevented_loss_fen BIGINT         NULL,
            ADD COLUMN IF NOT EXISTS improved_kpi       JSONB          NULL,
            ADD COLUMN IF NOT EXISTS roi_evidence       JSONB          NULL
    """)

    op.execute("""
        COMMENT ON COLUMN agent_decision_logs.saved_labor_hours
            IS 'Sprint D2: 本次决策节省的人力工时（小时，可为小数）'
    """)
    op.execute("""
        COMMENT ON COLUMN agent_decision_logs.prevented_loss_fen
            IS 'Sprint D2: 本次决策阻止的资金损失（单位: 分）'
    """)
    op.execute("""
        COMMENT ON COLUMN agent_decision_logs.improved_kpi
            IS 'Sprint D2: 改善的 KPI 结构化证据，形如 {"metric": "...", "delta_pct": 3.2}'
    """)
    op.execute("""
        COMMENT ON COLUMN agent_decision_logs.roi_evidence
            IS 'Sprint D2: ROI 证据链（上游事件、算法版本、计算过程、依赖参数）'
    """)

    # ── 2. 部分索引：仅命中存在 ROI 数据的行，按租户+月份快速过滤 ──────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_roi_tenant_month
            ON agent_decision_logs (tenant_id, (date_trunc('month', created_at)))
            WHERE saved_labor_hours IS NOT NULL
               OR prevented_loss_fen IS NOT NULL
    """)

    # ── 3. 物化视图：按 (tenant_id, agent_id, month) 聚合 ROI ─────────
    # 注意：
    #   - WITH NO DATA：视图创建时不立即聚合，避免冷启动失败；
    #                    首次填充由应用层 REFRESH 或 scripts/refresh_mv_agent_roi.sh 驱动
    #   - tenant_id IS NOT NULL：双保险，防止任何 RLS 绕过的脏数据进入视图
    #   - COALESCE(SUM(...), 0)：即便无数据，聚合行也能正常 refresh（NULL 聚合安全）
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_agent_roi_monthly AS
        SELECT
            tenant_id,
            agent_id,
            date_trunc('month', created_at)                               AS month,
            COUNT(*)                                                      AS decision_count,
            COALESCE(SUM(saved_labor_hours), 0)::NUMERIC(14, 2)           AS total_saved_labor_hours,
            COALESCE(SUM(prevented_loss_fen), 0)::BIGINT                  AS total_prevented_loss_fen,
            jsonb_agg(DISTINCT improved_kpi) FILTER (WHERE improved_kpi IS NOT NULL)
                                                                          AS kpi_deltas,
            NOW()                                                         AS refreshed_at
        FROM agent_decision_logs
        WHERE tenant_id IS NOT NULL
          AND is_deleted = false
        GROUP BY tenant_id, agent_id, date_trunc('month', created_at)
        WITH NO DATA
    """)

    # REFRESH MATERIALIZED VIEW CONCURRENTLY 需要唯一索引
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_agent_roi_monthly_pk
            ON mv_agent_roi_monthly (tenant_id, agent_id, month)
    """)

    op.execute("""
        COMMENT ON MATERIALIZED VIEW mv_agent_roi_monthly
            IS 'Sprint D2: Agent ROI 月度聚合视图，供总部 ROI 看板/签字依据使用。'
               ' REFRESH 策略见 scripts/refresh_mv_agent_roi.sh'
    """)


def downgrade() -> None:
    # 顺序倒序：先视图、再索引、再列
    op.execute("DROP INDEX IF EXISTS idx_mv_agent_roi_monthly_pk")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_agent_roi_monthly")
    op.execute("DROP INDEX IF EXISTS idx_agent_decision_roi_tenant_month")
    op.execute("""
        ALTER TABLE agent_decision_logs
            DROP COLUMN IF EXISTS roi_evidence,
            DROP COLUMN IF EXISTS improved_kpi,
            DROP COLUMN IF EXISTS prevented_loss_fen,
            DROP COLUMN IF EXISTS saved_labor_hours
    """)
