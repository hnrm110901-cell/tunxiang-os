"""v277 — 营销活动 ROI 预测表（Sprint D3b）

目标：MAPE < 20% 的活动真实增量预测

核心用例：
  1. **规划期**（plan）：活动未开始前，Prophet 预测"无活动基线" → uplift 估算
     → store `baseline_forecast_fen` + `uplift_forecast_fen` + `forecast_confidence`
  2. **活动期**（running）：持续收集 actual 写入 `actual_revenue_fen`
  3. **复盘期**（completed）：对比 baseline vs actual，算 true_uplift + MAPE
  4. **反馈回路**：MAPE > 20% 的 campaign 自动标记 `needs_calibration=true`，
     下一轮训练时剔除，避免脏数据污染模型

Revision ID: v277_campaign_roi
Revises: v276
Create Date: 2026-04-23
"""
from alembic import op

revision = "v277_campaign_roi"
down_revision = "v276"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 主表
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_roi_forecasts (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            store_id                    UUID,
            campaign_id                 UUID,                -- 关联 marketing_campaigns.id（未来建）
            campaign_name               VARCHAR(200) NOT NULL,
            campaign_type               VARCHAR(50) NOT NULL,
                                        -- seasonal / referral / offpeak / new_customer / dormant_recall / banquet
            -- 时间窗
            forecast_start              DATE NOT NULL,
            forecast_end                DATE NOT NULL,
                                        CHECK (forecast_end >= forecast_start),
            -- 模型与版本
            forecast_model              VARCHAR(50) NOT NULL DEFAULT 'prophet',
                                        -- prophet / linear / moving_average（fallback）
            model_version               VARCHAR(30),
            -- 预测值（分）
            baseline_forecast_fen       BIGINT NOT NULL DEFAULT 0
                                        CHECK (baseline_forecast_fen >= 0),
            uplift_forecast_fen         BIGINT NOT NULL DEFAULT 0,
                                        -- 可负（活动可能预估拉低自然客流）
            forecast_confidence         NUMERIC(4,3) NOT NULL DEFAULT 0
                                        CHECK (forecast_confidence >= 0 AND forecast_confidence <= 1),
            -- 实际值（分，活动结束后回填）
            actual_revenue_fen          BIGINT,
            actual_baseline_fen         BIGINT,
                                        -- 从未参加活动的平行门店/时段数据反推
            true_uplift_fen             BIGINT,
            -- 评估指标
            mape                        NUMERIC(6,3),        -- Mean Absolute Percentage Error 0-1
            needs_calibration           BOOLEAN NOT NULL DEFAULT FALSE,
                                        -- MAPE > 0.20 时置 true，下轮训练剔除
            -- Sonnet 分析（调用 claude-sonnet-4-6）
            sonnet_analysis             TEXT,
                                        -- 文本分析："为什么预测偏高/低？"
            recommended_actions         JSONB DEFAULT '[]'::jsonb,
                                        -- [{"action": "降低折扣幅度", "expected_lift_fen": -500, "priority": "high"}]
            -- 证据链
            training_data_snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb,
                                        -- {"data_points": 180, "training_window_days": 90, "features": [...]}
            -- 状态流
            status                      VARCHAR(30) NOT NULL DEFAULT 'plan'
                                        CHECK (status IN (
                                            'plan',         -- 规划期（仅 forecast）
                                            'running',      -- 活动进行中
                                            'completed',    -- 已复盘
                                            'cancelled',    -- 活动取消
                                            'error'
                                        )),
            -- 基础字段
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 2. 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_roi_tenant_status
            ON campaign_roi_forecasts (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_roi_store_window
            ON campaign_roi_forecasts (tenant_id, store_id, forecast_start, forecast_end)
            WHERE is_deleted = false
    """)
    # 需校准的 campaign 快速扫描（下轮训练剔除脏数据）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_roi_needs_calibration
            ON campaign_roi_forecasts (tenant_id, needs_calibration)
            WHERE needs_calibration = true AND is_deleted = false
    """)

    # 3. RLS
    op.execute("ALTER TABLE campaign_roi_forecasts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS campaign_roi_tenant_isolation ON campaign_roi_forecasts;
        CREATE POLICY campaign_roi_tenant_isolation ON campaign_roi_forecasts
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 4. 注释
    op.execute("""
        COMMENT ON TABLE campaign_roi_forecasts IS
            'Sprint D3b: 营销活动 ROI 预测（Prophet + Sonnet），目标 MAPE < 20%';
        COMMENT ON COLUMN campaign_roi_forecasts.baseline_forecast_fen IS
            'Prophet 预测的无活动基线营收（分）';
        COMMENT ON COLUMN campaign_roi_forecasts.uplift_forecast_fen IS
            '活动带来的增量预测（actual - baseline），可为负';
        COMMENT ON COLUMN campaign_roi_forecasts.mape IS
            'Mean Absolute Percentage Error 0-1，> 0.20 触发 needs_calibration';
        COMMENT ON COLUMN campaign_roi_forecasts.sonnet_analysis IS
            'Sonnet 生成的文本分析：为何偏离/建议调整/风险点';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_roi_forecasts CASCADE")
