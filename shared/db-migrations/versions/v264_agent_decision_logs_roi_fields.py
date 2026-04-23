"""v264 — agent_decision_logs ROI 三字段 + 证据 JSONB（Sprint D2）

为 Agent 决策引入可量化 ROI 追踪，解决"Agent 做了 100 件事，但没人知道省了多少钱"
的问题。每条决策记录都自带：

  saved_labor_hours   NUMERIC(10,2)  —— 节省人力工时（分析/跑腿/盘点替代）
  prevented_loss_fen  BIGINT         —— 拦截的损失金额（违规折扣/食安违规/过期浪费/重复支付）
  improved_kpi        JSONB          —— 正向 KPI 变化（{"revenue_uplift_fen": 500, "nps_delta": 0.3}）
  roi_evidence        JSONB          —— 证据链（数据源 URL/SQL/事件 ID，便于 audit）

Revision ID: v264_roi
Revises: v263
Create Date: 2026-04-23
"""
from alembic import op

revision = "v264_roi"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 添加 4 列（使用 IF NOT EXISTS 兼容重复迁移）
    op.execute("""
        ALTER TABLE agent_decision_logs
            ADD COLUMN IF NOT EXISTS saved_labor_hours   NUMERIC(10,2) DEFAULT 0,
            ADD COLUMN IF NOT EXISTS prevented_loss_fen  BIGINT        DEFAULT 0,
            ADD COLUMN IF NOT EXISTS improved_kpi        JSONB         DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS roi_evidence        JSONB         DEFAULT '{}'::jsonb
    """)

    # 2. 非负约束（CHECK）
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_agent_decision_logs_saved_labor_hours_nonneg'
            ) THEN
                ALTER TABLE agent_decision_logs
                    ADD CONSTRAINT chk_agent_decision_logs_saved_labor_hours_nonneg
                    CHECK (saved_labor_hours >= 0);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_agent_decision_logs_prevented_loss_nonneg'
            ) THEN
                ALTER TABLE agent_decision_logs
                    ADD CONSTRAINT chk_agent_decision_logs_prevented_loss_nonneg
                    CHECK (prevented_loss_fen >= 0);
            END IF;
        END $$
    """)

    # 3. 覆盖索引：按 tenant + month 查 ROI 聚合（mv_agent_roi_monthly 读此索引）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_logs_roi_monthly
            ON agent_decision_logs (
                tenant_id,
                DATE_TRUNC('month', decided_at),
                agent_id
            )
            WHERE is_deleted = false
              AND (saved_labor_hours > 0 OR prevented_loss_fen > 0
                   OR improved_kpi <> '{}'::jsonb)
    """)

    # 4. 列注释（便于运维查 \d+ agent_decision_logs）
    op.execute("""
        COMMENT ON COLUMN agent_decision_logs.saved_labor_hours IS
            '节省的人力工时（分析/盘点/跑腿代替，单位小时）';
        COMMENT ON COLUMN agent_decision_logs.prevented_loss_fen IS
            '拦截的损失（违规折扣/食安/浪费/重复扣款，单位分）';
        COMMENT ON COLUMN agent_decision_logs.improved_kpi IS
            'KPI 正向变化，如 {"revenue_uplift_fen": 500, "nps_delta": 0.3}';
        COMMENT ON COLUMN agent_decision_logs.roi_evidence IS
            '证据链：数据源 URL / SQL / 事件 ID / 验证方式，便于审计核验';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_decision_logs_roi_monthly")
    op.execute("""
        ALTER TABLE agent_decision_logs
            DROP CONSTRAINT IF EXISTS chk_agent_decision_logs_saved_labor_hours_nonneg,
            DROP CONSTRAINT IF EXISTS chk_agent_decision_logs_prevented_loss_nonneg,
            DROP COLUMN IF EXISTS roi_evidence,
            DROP COLUMN IF EXISTS improved_kpi,
            DROP COLUMN IF EXISTS prevented_loss_fen,
            DROP COLUMN IF EXISTS saved_labor_hours
    """)
