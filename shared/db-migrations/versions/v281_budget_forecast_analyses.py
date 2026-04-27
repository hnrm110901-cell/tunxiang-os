"""v281 — 预算预测分析表（Sprint D4c）

目标：月度/季度 CFO 做下期预算时，Sonnet 4.7 基于历史 P&L + 行业 benchmark
     预测下月/下季品牌或门店的成本结构异常，给出 variance 预警 + 预防动作。

业务场景：
  1. **食材成本上行**：冬季涨价（海鲜/青菜）+ 供应商涨价 → 预警下月食材占比超阈值
  2. **人工成本踩线**：最低工资上调 + 排班扩张 → 预警人工占比 >30% 红线
  3. **租金/能耗突增**：空调高峰月 / 续签涨租 → 预测变动 vs 历史
  4. **营收预测偏差**：季节/节日/竞对开店影响 → 基于同店同月基准校验
  5. **净利率断崖**：多因素叠加 → 预警下期可能负毛利

工作流：
  1. 每月 25 号 cron 扫描近 12 个月 payroll_summaries + pnl_reports
     → 生成 BudgetSignalBundle（含历史 P&L 快照）
  2. Sonnet 4.7 + Prompt Cache（行业 P&L benchmark ~3KB cacheable）预测
  3. 输出 predicted_line_items + variance_risks + preventive_actions
  4. CFO 审核 → approve / revise / escalate

与 D4a/D4b 共用 CachedPromptBuilder 模式：
  · 第 1 段 STABLE_SYSTEM：预算预测 JSON schema（跨租户稳定）
  · 第 2 段 PNL_BENCHMARKS：行业 P&L 基准（正餐 / 快餐 / 茶饮 三类
    目标食材占比 / 人工占比 / 租金占比 / 净利率）
多店多季度分析共享同一段 cache → 命中率目标 ≥ 75%。

Revision ID: v281_budget_forecast
Revises: v280_salary_anomaly
Create Date: 2026-04-23
"""
from alembic import op

revision = "v281_budget_forecast"
down_revision = "v280_salary_anomaly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_forecast_analyses (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            brand_id                UUID,
            store_id                UUID,
                                    -- 两者都 NULL 表示集团级；brand_id 填 = 品牌级；store_id 填 = 门店级
            -- 预测窗口
            forecast_month          DATE NOT NULL,
                                    -- 预测期首日 YYYY-MM-01
            forecast_scope          VARCHAR(30) NOT NULL DEFAULT 'monthly_store'
                                    CHECK (forecast_scope IN (
                                        'monthly_brand',    -- 品牌级月度
                                        'monthly_store',    -- 单店月度
                                        'quarterly_brand',  -- 品牌级季度
                                        'adhoc'             -- 手动触发（临时方案）
                                    )),
            history_months          INTEGER NOT NULL DEFAULT 12
                                    CHECK (history_months BETWEEN 3 AND 36),
                                    -- 用于训练的历史窗口
            -- 业态基准
            business_type           VARCHAR(30) NOT NULL DEFAULT 'full_service'
                                    CHECK (business_type IN (
                                        'full_service',    -- 正餐
                                        'quick_service',   -- 快餐
                                        'tea_beverage',    -- 茶饮
                                        'buffet',          -- 自助
                                        'hot_pot'          -- 火锅
                                    )),
            -- 上下文快照
            history_snapshot        JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- {months: [{month, revenue, food_cost, labor_cost, rent, utility, other, net}], ...}
            -- Sonnet 输出
            predicted_line_items    JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{line_item, predicted_fen, ratio_of_revenue, confidence_low, confidence_high}]
            variance_risks          JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{line_item, risk_type, severity, delta_fen, evidence, legal_flag}]
            preventive_actions      JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{action, owner_role, deadline_days, expected_saving_fen}]
            sonnet_analysis         TEXT,
            -- 聚合指标（用于 summary API）
            predicted_revenue_fen   BIGINT NOT NULL DEFAULT 0
                                    CHECK (predicted_revenue_fen >= 0),
            predicted_net_fen       BIGINT NOT NULL DEFAULT 0,
                                    -- 允许负值（预警亏损）
            predicted_margin_pct    NUMERIC(6,4) NOT NULL DEFAULT 0,
            -- Prompt Cache 统计（D4 共用指标）
            model_id                VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet-4-7',
            cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
            input_tokens            INTEGER NOT NULL DEFAULT 0,
            output_tokens           INTEGER NOT NULL DEFAULT 0,
            -- 状态流（CFO 审核）
            status                  VARCHAR(30) NOT NULL DEFAULT 'analyzed'
                                    CHECK (status IN (
                                        'pending',      -- 预测中
                                        'analyzed',     -- 已出预测
                                        'approved',     -- CFO 采纳
                                        'revised',      -- CFO 修订后生效
                                        'escalated',    -- 升级到 CEO
                                        'error'
                                    )),
            reviewed_by             UUID,
            reviewed_at             TIMESTAMPTZ,
            revision_note           TEXT,
                                    -- CFO 修订时填写，解释调整原因
            -- 基础字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 唯一：同月同 scope 同门店（或品牌）只一条（幂等）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_budget_forecast_monthly
            ON budget_forecast_analyses (
                tenant_id,
                COALESCE(brand_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid),
                forecast_month,
                forecast_scope
            )
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_budget_forecast_tenant_status
            ON budget_forecast_analyses (tenant_id, status, forecast_month DESC)
            WHERE is_deleted = false
    """)
    # CFO 审核队列：escalated/analyzed 按创建时间倒序
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_budget_forecast_review_queue
            ON budget_forecast_analyses (tenant_id, created_at DESC)
            WHERE status IN ('analyzed', 'escalated') AND is_deleted = false
    """)

    # RLS
    op.execute("ALTER TABLE budget_forecast_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS budget_forecast_tenant_isolation ON budget_forecast_analyses;
        CREATE POLICY budget_forecast_tenant_isolation ON budget_forecast_analyses
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE budget_forecast_analyses IS
            'Sprint D4c: 预算预测，Sonnet 4.7 + Prompt Cache 共享行业 P&L benchmark，
             月度/季度 CFO 审核，提前预警成本结构恶化';
        COMMENT ON COLUMN budget_forecast_analyses.predicted_line_items IS
            '[{line_item: revenue|food_cost|labor_cost|rent|utility|other|net,
              predicted_fen, ratio_of_revenue, confidence_low, confidence_high}]';
        COMMENT ON COLUMN budget_forecast_analyses.variance_risks IS
            '[{line_item, risk_type: cost_overrun|revenue_drop|margin_compression|compliance_breach,
              severity: critical|high|medium|low, delta_fen, evidence, legal_flag}]';
        COMMENT ON COLUMN budget_forecast_analyses.cache_read_tokens IS
            '与 D4a/D4b 共用 CachedPromptBuilder 模式，多分析共享 P&L benchmark cache';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_forecast_analyses CASCADE")
