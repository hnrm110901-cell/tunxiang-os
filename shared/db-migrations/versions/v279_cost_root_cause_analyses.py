"""v279 — 成本根因分析表（Sprint D4a）

目标：月底成本超预算 5% 时，Agent 自动分析根因，减少店长人工翻表时间。

工作流：
  1. 触发：月底 cron 扫描 mv_store_pnl，food_cost_rate 超预算 5% 的门店进入候选
  2. 收集：近 30 天原料采购（tx-supply）/BOM 损耗（tx-supply）/浪费登记（tx-ops）/
        供应商价格变动（tx-supply）→ 结构化信号包
  3. 分析：Sonnet 4.7 + Prompt Cache（system prompt 含 BOM catalog + 行业基准常量，
        cache_control=ephemeral 5min TTL，后续 10 个门店分析共享 cache）
  4. 输出：ranked_causes（原料涨价/浪费率升高/BOM 偏差/违规采购）+ 每条证据 + 建议

成本测算（1 月 10 店）：
  - System prompt ~3000 tokens × 10 次分析 = 30K cache-read tokens
  - User prompt (门店签名信号包) ~1000 tokens × 10 次 = 10K input tokens
  - Response ~500 tokens × 10 = 5K output tokens
  - 无 cache: 30K input × $3/M + 5K output × $15/M = ¥0.65/月
  - With cache: 30K cache-read × $0.3/M + 10K input × $3/M + 5K × $15/M = ¥0.18/月
  - **缓存命中 ≥75% 时成本降 70%+**（符合设计稿"模型成本月上限 ¥12,000"）

Revision ID: v279_cost_root_cause
Revises: v278
Create Date: 2026-04-23
"""
from alembic import op

revision = "v279_cost_root_cause"
down_revision = "v278"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS cost_root_cause_analyses (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            -- 触发窗口
            analysis_month          DATE NOT NULL,
                                    -- YYYY-MM-01
            analysis_type           VARCHAR(40) NOT NULL DEFAULT 'monthly_cost_overrun'
                                    CHECK (analysis_type IN (
                                        'monthly_cost_overrun',   -- 月底成本超支触发
                                        'sudden_cost_spike',      -- 日环比突增
                                        'manual'                  -- 店长手动触发
                                    )),
            -- 上下文
            food_cost_fen           BIGINT NOT NULL DEFAULT 0,
            food_cost_budget_fen    BIGINT NOT NULL DEFAULT 0,
            cost_overrun_pct        NUMERIC(6,3) NOT NULL DEFAULT 0,
                                    -- (actual - budget) / budget
            signals_snapshot        JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- {raw_materials: [...], waste: [...], bom_deviation: [...],
                                    --  supplier_price_changes: [...]}
            -- Sonnet 输出
            ranked_causes           JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{cause_type, confidence, evidence, impact_fen, priority}]
            remediation_actions     JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{action, owner_role, deadline_days, expected_savings_fen}]
            sonnet_analysis         TEXT,
            -- Prompt Cache 统计（验证 ≥75% 目标）
            model_id                VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet-4-7',
            cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
            input_tokens            INTEGER NOT NULL DEFAULT 0,
            output_tokens           INTEGER NOT NULL DEFAULT 0,
            -- 状态流
            status                  VARCHAR(30) NOT NULL DEFAULT 'analyzed'
                                    CHECK (status IN (
                                        'pending',       -- 已触发，分析中
                                        'analyzed',      -- 分析完成
                                        'acted_on',      -- 店长已采纳
                                        'dismissed',     -- 店长标记为误报
                                        'error'
                                    )),
            reviewed_by             UUID,
            reviewed_at             TIMESTAMPTZ,
            -- 基础字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 唯一约束：同月同店只有一条（manual 可多条，用 analysis_type 放宽）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_cost_root_cause_monthly
            ON cost_root_cause_analyses (tenant_id, store_id, analysis_month)
            WHERE analysis_type = 'monthly_cost_overrun' AND is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_root_cause_tenant_status
            ON cost_root_cause_analyses (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    # 用于统计 prompt cache 命中率
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_root_cause_cache_stats
            ON cost_root_cause_analyses (tenant_id, created_at DESC)
            WHERE is_deleted = false
              AND (cache_read_tokens > 0 OR cache_creation_tokens > 0)
    """)

    # RLS
    op.execute("ALTER TABLE cost_root_cause_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS cost_root_cause_tenant_isolation ON cost_root_cause_analyses;
        CREATE POLICY cost_root_cause_tenant_isolation ON cost_root_cause_analyses
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE cost_root_cause_analyses IS
            'Sprint D4a: 成本根因分析，Sonnet 4.7 + Prompt Cache，每月触发按店输出排名原因 + 治理建议';
        COMMENT ON COLUMN cost_root_cause_analyses.ranked_causes IS
            '排名根因：[{cause_type, confidence 0-1, evidence, impact_fen, priority: high/med/low}]';
        COMMENT ON COLUMN cost_root_cause_analyses.cache_read_tokens IS
            'Prompt Cache 命中字数，用于验证"缓存命中 ≥75%"设计目标';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cost_root_cause_analyses CASCADE")
