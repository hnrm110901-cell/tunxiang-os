"""v278 — 菜品动态定价建议表（Sprint D3c）

目标：毛利 +2pp（通过分级调价 + 毛利底线 15% 硬约束）

核心工作流：
  1. **弹性估算**（hourly/daily）：从 order_items 聚合，算 log-log 价格弹性
  2. **最优价格求解**：subject to 毛利率 ≥ 15% + 变动幅度 ≤ 15%
  3. **Sonnet 语义校验**：Core ML/弹性回归出数值，Sonnet 看品牌调性/客户感知
  4. **店长审批**：plan → human_confirmed → applied
  5. **效果回测**：应用后 7-14 天对比实际毛利变化

Revision ID: v278_dish_pricing
Revises: v277
Create Date: 2026-04-23
"""
from alembic import op

revision = "v278_dish_pricing"
down_revision = "v277"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 主表
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_pricing_suggestions (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID,
            dish_id                 UUID NOT NULL,
            dish_name               VARCHAR(200) NOT NULL,
            -- 当前 vs 建议
            current_price_fen       BIGINT NOT NULL CHECK (current_price_fen > 0),
            suggested_price_fen     BIGINT NOT NULL CHECK (suggested_price_fen > 0),
            current_cost_fen        BIGINT NOT NULL CHECK (current_cost_fen >= 0),
            current_margin_rate     NUMERIC(5,4) NOT NULL
                                    CHECK (current_margin_rate >= -1 AND current_margin_rate <= 1),
            suggested_margin_rate   NUMERIC(5,4) NOT NULL
                                    CHECK (suggested_margin_rate >= 0 AND suggested_margin_rate <= 1),
            price_change_pct        NUMERIC(6,3) NOT NULL,
                                    -- 可为负（降价）
            -- 弹性
            elasticity              NUMERIC(7,4),
                                    -- 价格弹性系数，负值表示涨价使需求下降（典型 -0.5 ~ -2.0）
            elasticity_confidence   NUMERIC(4,3) NOT NULL DEFAULT 0
                                    CHECK (elasticity_confidence >= 0 AND elasticity_confidence <= 1),
            elasticity_source       VARCHAR(30) NOT NULL DEFAULT 'log_log'
                                    CHECK (elasticity_source IN (
                                        'log_log',         -- 对数-对数回归
                                        'coreml',          -- Core ML 边缘推理
                                        'prior',           -- 先验值 -1.0
                                        'insufficient'
                                    )),
            -- 预估影响
            expected_daily_qty_delta INTEGER NOT NULL DEFAULT 0,
                                    -- 预估日销量变化（正=增长，负=下降）
            expected_daily_margin_delta_fen BIGINT NOT NULL DEFAULT 0,
                                    -- 预估日毛利变化（分，正=增长）
            -- 硬约束校验
            constraint_check        JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- {"margin_floor_passed": true, "change_pct_within_15": true}
            -- Sonnet 分析
            sonnet_analysis         TEXT,
            sonnet_risk_level       VARCHAR(10)
                                    CHECK (sonnet_risk_level IN ('low', 'medium', 'high')),
            -- 状态流
            status                  VARCHAR(30) NOT NULL DEFAULT 'plan'
                                    CHECK (status IN (
                                        'plan',             -- 规划期
                                        'human_confirmed',  -- 店长确认
                                        'applied',          -- 已应用到 dishes.price_fen
                                        'reverted',         -- 回滚
                                        'rejected',         -- 店长拒绝
                                        'expired'           -- 超过 7 天未处理
                                    )),
            -- 审批
            confirmed_by            UUID,
            confirmed_at            TIMESTAMPTZ,
            applied_at              TIMESTAMPTZ,
            reverted_at             TIMESTAMPTZ,
            -- 效果回测（应用 7-14 天后回填）
            actual_qty_delta        INTEGER,
            actual_margin_delta_fen BIGINT,
            backtest_at             TIMESTAMPTZ,
            -- 基础字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 2. 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_pricing_tenant_status
            ON dish_pricing_suggestions (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_pricing_store_dish
            ON dish_pricing_suggestions (tenant_id, store_id, dish_id, created_at DESC)
            WHERE is_deleted = false
    """)
    # 待店长审批（plan）快速扫描
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_pricing_pending_approval
            ON dish_pricing_suggestions (tenant_id, store_id, created_at DESC)
            WHERE status = 'plan' AND is_deleted = false
    """)

    # 3. RLS
    op.execute("ALTER TABLE dish_pricing_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dish_pricing_tenant_isolation ON dish_pricing_suggestions;
        CREATE POLICY dish_pricing_tenant_isolation ON dish_pricing_suggestions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 4. 注释
    op.execute("""
        COMMENT ON TABLE dish_pricing_suggestions IS
            'Sprint D3c: 菜品动态定价建议，弹性+最优解+Sonnet 校验+店长审批，目标毛利 +2pp';
        COMMENT ON COLUMN dish_pricing_suggestions.elasticity IS
            '价格弹性系数，典型 -0.5 ~ -2.0，负值越大表示需求对涨价越敏感';
        COMMENT ON COLUMN dish_pricing_suggestions.elasticity_source IS
            'log_log=对数回归 / coreml=边缘推理 / prior=先验 / insufficient=数据不足';
        COMMENT ON COLUMN dish_pricing_suggestions.expected_daily_margin_delta_fen IS
            '预估日毛利变化（分），应用后 14 天与 actual_margin_delta_fen 回测';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dish_pricing_suggestions CASCADE")
