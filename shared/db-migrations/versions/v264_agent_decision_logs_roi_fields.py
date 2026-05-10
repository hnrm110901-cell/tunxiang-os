"""v264 — agent_decision_logs ROI 三字段 + 证据 JSONB（Sprint D2）

为 Agent 决策引入可量化 ROI 追踪，解决"Agent 做了 100 件事，但没人知道省了多少钱"
的问题。每条决策记录都自带：

  saved_labor_hours   NUMERIC(10,2)  —— 节省人力工时（分析/跑腿/盘点替代）
  prevented_loss_fen  BIGINT         —— 拦截的损失金额（违规折扣/食安违规/过期浪费/重复支付）
  improved_kpi        JSONB          —— 正向 KPI 变化（{"revenue_uplift_fen": 500, "nps_delta": 0.3}）
  roi_evidence        JSONB          —— 证据链（数据源 URL/SQL/事件 ID，便于 audit）

Revision ID: v264_roi
Revises: v264 (chain serialization, see PR #352 - v264 multi-head debt)
Create Date: 2026-04-23

Chain repair note (PR #352):
  原 down_revision = "v263"，与 v264_agent_roi_fields.py 形成两个 v263 子分叉，
  都改同一张 agent_decision_logs 表。两 migration 均用 ADD COLUMN IF NOT EXISTS
  对相同 4 列幂等添加（v264 用 NULL 默认，本文件用 DEFAULT 0），whoever runs first
  wins. Index 不同 (v264 索引 created_at / 本文件索引 decided_at + agent_id)，二者
  互补不冲突，runtime 都需要。

  本次 chain serialization：把 down_revision 改为 "v264"（v264 先跑添加列与默认 NULL，
  本文件后跑因 IF NOT EXISTS 跳过 ADD COLUMN，但补加 decided_at 索引），让 v263
  → v264 → v264_roi → v265_mv_agent_roi_monthly 链路 deterministic，不再受 alembic
  随机拓扑序影响。schema 终态等价 v264 winning + 索引 v264 + v264_roi 各 1 个。

  独立 fork 仍保留 (v264b/v264c/v265/v266_mem_evo) — 它们改不同表，是合法 parallel
  feature。Phase 4a-4 baseline squash 后整链重写时彻底清理。
"""
from alembic import op

revision = "v264_roi"
down_revision = "v264"  # 原 "v263"，PR #352 chain serialization 见 docstring
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

    # 3. 覆盖索引：按 tenant + 时间 + agent 查 ROI 聚合（mv_agent_roi_monthly 读此索引）
    # 修 (PR #346): 原索引含 `DATE_TRUNC('month', decided_at)` — PG 拒（STABLE 不是
    # IMMUTABLE）。改裸列 (tenant_id, decided_at DESC, agent_id)；查询侧用范围过滤
    # `decided_at >= start_of_month AND < start_of_next_month` 等价命中索引。
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_logs_roi_monthly
            ON agent_decision_logs (
                tenant_id,
                decided_at DESC,
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
