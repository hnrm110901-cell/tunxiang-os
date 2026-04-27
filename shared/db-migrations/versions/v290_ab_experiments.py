"""v290 — A/B 实验框架（Sprint G）

目标：实验平台，支持：
  · 流量切分（deterministic hash-based assignment）
  · 统计显著性（Frequentist z-test + Bayesian posterior）
  · 熔断器（treatment 劣于 control >20% 自动终止）
  · 跨租户租户级隔离 + 租户级 rollout percentage

4 张表：
  · `ab_experiments` — 实验定义 + 配置 + 生命周期状态
  · `ab_experiment_arms` — 实验下各 arm 定义（control + treatments）
  · `ab_experiment_assignments` — (entity_id, experiment_id) → arm_id 稳定分配
  · `ab_experiment_events` — 暴露 + 转化 + 结果事件（append-only）

物化视图（本迁移只建表，视图由投影器异步生成）：
  · `mv_ab_experiment_stats_daily` — 每日按 arm 聚合 exposure/conversion/revenue

Sprint plan 对齐：Sprint G A/B 框架（W6-8），Week 8 Go/No-Go § 9 要求：
  至少 1 个 A/B 实验 running 未熔断

Revision ID: v290_ab_experiments
Revises: v288_delivery_disputes
Create Date: 2026-04-24
"""
from alembic import op

revision = "v290_ab_experiments"
down_revision = "v288_delivery_disputes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. ab_experiments ────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_experiments (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            experiment_key          VARCHAR(100) NOT NULL,
                                    -- 业务键，同租户内唯一（如 menu_recommend_v2_vs_v1）
            name                    VARCHAR(200) NOT NULL,
            description             TEXT,
            -- 实验目标（影响显著性判定）
            primary_metric          VARCHAR(50) NOT NULL DEFAULT 'conversion_rate'
                                    CHECK (primary_metric IN (
                                        'conversion_rate',     -- 转化率
                                        'avg_revenue',         -- 平均单价
                                        'aov',                 -- average order value
                                        'retention_7d',        -- 7 日留存
                                        'complaint_rate',      -- 投诉率
                                        'gross_margin_pct',    -- 毛利率
                                        'custom'               -- 自定义（走 numeric_value）
                                    )),
            primary_metric_goal     VARCHAR(10) NOT NULL DEFAULT 'maximize'
                                    CHECK (primary_metric_goal IN ('maximize', 'minimize')),
            -- 分配策略
            assignment_strategy     VARCHAR(30) NOT NULL DEFAULT 'deterministic_hash'
                                    CHECK (assignment_strategy IN (
                                        'deterministic_hash',  -- hash(entity + experiment) % 100
                                        'rollout_percentage',  -- 按 traffic_pct 控制曝光
                                        'tenant_ring'          -- 预先指定 tenant 列表
                                    )),
            entity_type             VARCHAR(30) NOT NULL DEFAULT 'customer'
                                    CHECK (entity_type IN (
                                        'customer',   -- 会员/顾客级
                                        'order',      -- 订单级
                                        'session',    -- 访问会话
                                        'store',      -- 门店级
                                        'device'      -- 设备级（anonymous）
                                    )),
            -- 流量
            traffic_percentage      NUMERIC(5,2) NOT NULL DEFAULT 100.00
                                    CHECK (traffic_percentage >= 0 AND traffic_percentage <= 100),
                                    -- 进入实验的总流量占比（未进入者走默认行为）
            -- 样本量与统计参数
            minimum_sample_size     INTEGER NOT NULL DEFAULT 1000
                                    CHECK (minimum_sample_size > 0),
            significance_level      NUMERIC(4,3) NOT NULL DEFAULT 0.050
                                    CHECK (significance_level > 0 AND significance_level < 0.5),
                                    -- alpha，默认 0.05
            power                   NUMERIC(4,3) NOT NULL DEFAULT 0.800
                                    CHECK (power > 0 AND power < 1),
                                    -- 1 - beta，用于 sample size 计算
            min_detectable_effect   NUMERIC(4,3) NOT NULL DEFAULT 0.050,
                                    -- 最小可检测效应（5%）
            -- 熔断
            circuit_breaker_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            circuit_breaker_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.200,
                                    -- treatment 劣于 control 超过 20% 触发熔断
            circuit_breaker_min_samples INTEGER NOT NULL DEFAULT 200,
                                    -- 最小 exposure 达此值后才评估熔断（避免早期噪声）
            circuit_breaker_tripped BOOLEAN NOT NULL DEFAULT FALSE,
            circuit_breaker_tripped_at TIMESTAMPTZ,
            circuit_breaker_tripped_reason TEXT,
            -- 生命周期状态
            status                  VARCHAR(30) NOT NULL DEFAULT 'draft'
                                    CHECK (status IN (
                                        'draft',                       -- 配置中
                                        'running',                     -- 运行中
                                        'paused',                      -- 暂停（流量归零但历史保留）
                                        'terminated_winner',           -- 某 arm 统计显著胜出
                                        'terminated_no_winner',        -- 所有 arm 无显著差异
                                        'terminated_circuit_breaker',  -- 熔断终止
                                        'completed',                   -- 达到 sample size + p 值
                                        'archived',                    -- 归档（终态）
                                        'error'
                                    )),
            winner_arm_id           UUID,
                                    -- 胜出 arm（terminated_winner / completed 时填）
            -- 时间
            started_at              TIMESTAMPTZ,
            ended_at                TIMESTAMPTZ,
            -- 审计
            created_by              UUID,
            approved_by             UUID,
            approved_at             TIMESTAMPTZ,
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 同租户内 experiment_key 唯一
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ab_experiments_key
            ON ab_experiments (tenant_id, experiment_key)
            WHERE is_deleted = false
    """)
    # 运营看板：running / status 查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_experiments_status
            ON ab_experiments (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    # 熔断监控：running + circuit_breaker 待触发
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_experiments_circuit_monitor
            ON ab_experiments (tenant_id, status)
            WHERE is_deleted = false
              AND status = 'running'
              AND circuit_breaker_enabled = true
              AND circuit_breaker_tripped = false
    """)

    op.execute("ALTER TABLE ab_experiments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ab_experiments_tenant_isolation ON ab_experiments;
        CREATE POLICY ab_experiments_tenant_isolation ON ab_experiments
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. ab_experiment_arms ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_experiment_arms (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            experiment_id           UUID NOT NULL
                                    REFERENCES ab_experiments(id)
                                    ON DELETE CASCADE,
            arm_key                 VARCHAR(50) NOT NULL,
                                    -- 'control' / 'treatment_v2' / 'treatment_high_price'
            name                    VARCHAR(100) NOT NULL,
            description             TEXT,
            is_control              BOOLEAN NOT NULL DEFAULT FALSE,
            -- 分配权重（相对比例，0-100；所有 arms 权重可不等 100，归一化）
            traffic_weight          INTEGER NOT NULL DEFAULT 50
                                    CHECK (traffic_weight >= 0 AND traffic_weight <= 100),
            -- 实验参数（下发给业务层）
            parameters              JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- 如 {template_id: 'v2', discount_pct: 15}
            -- 统计（由投影器更新）
            exposure_count          BIGINT NOT NULL DEFAULT 0,
                                    -- 暴露人次（分母）
            conversion_count        BIGINT NOT NULL DEFAULT 0,
                                    -- 转化人次（分子）
            revenue_sum_fen         BIGINT NOT NULL DEFAULT 0,
                                    -- 累计营收（continuous metric 用）
            numeric_metric_sum      NUMERIC(15,4) NOT NULL DEFAULT 0,
                                    -- 自定义连续指标累计（如毛利率 × 样本数）
            numeric_metric_ssq      NUMERIC(20,4) NOT NULL DEFAULT 0,
                                    -- sum of squares（用于方差计算）
            last_stats_refreshed_at TIMESTAMPTZ,
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 同实验 arm_key 唯一
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ab_arms_key
            ON ab_experiment_arms (experiment_id, arm_key)
            WHERE is_deleted = false
    """)
    # 按 experiment 拉 arms 列表（常用）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_arms_experiment
            ON ab_experiment_arms (tenant_id, experiment_id)
            WHERE is_deleted = false
    """)
    # 每实验最多 1 个 control
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ab_arms_one_control
            ON ab_experiment_arms (experiment_id)
            WHERE is_control = true AND is_deleted = false
    """)

    op.execute("ALTER TABLE ab_experiment_arms ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ab_arms_tenant_isolation ON ab_experiment_arms;
        CREATE POLICY ab_arms_tenant_isolation ON ab_experiment_arms
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. ab_experiment_assignments（稳定分配）─────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_experiment_assignments (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            experiment_id           UUID NOT NULL
                                    REFERENCES ab_experiments(id)
                                    ON DELETE CASCADE,
            arm_id                  UUID NOT NULL
                                    REFERENCES ab_experiment_arms(id)
                                    ON DELETE CASCADE,
            -- 被分配的业务实体
            entity_type             VARCHAR(30) NOT NULL,
                                    -- 冗余自 experiment，便于反查
            entity_id               VARCHAR(100) NOT NULL,
                                    -- customer_id / order_id / session_id / store_id / device_id
            -- 分配时的 hash（用于审计 + 调试）
            assignment_hash         INTEGER,
            -- 审计
            assigned_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            first_exposed_at        TIMESTAMPTZ,
            -- 基础（assignments 一般不软删；硬删 = 重新分配）
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 稳定分配：同 (tenant, experiment, entity) 只一条
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ab_assignments_entity
            ON ab_experiment_assignments (tenant_id, experiment_id, entity_type, entity_id)
    """)
    # 按 entity 拉所有实验分配（反查"某顾客参与了哪些实验"）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_assignments_entity
            ON ab_experiment_assignments (tenant_id, entity_type, entity_id, assigned_at DESC)
    """)
    # 按 arm 统计（运维查 arm 的样本量）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_assignments_arm
            ON ab_experiment_assignments (arm_id, assigned_at DESC)
    """)

    op.execute("ALTER TABLE ab_experiment_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ab_assignments_tenant_isolation ON ab_experiment_assignments;
        CREATE POLICY ab_assignments_tenant_isolation ON ab_experiment_assignments
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. ab_experiment_events（事件流，append-only）───────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_experiment_events (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            experiment_id           UUID NOT NULL
                                    REFERENCES ab_experiments(id)
                                    ON DELETE CASCADE,
            arm_id                  UUID NOT NULL
                                    REFERENCES ab_experiment_arms(id)
                                    ON DELETE CASCADE,
            entity_type             VARCHAR(30) NOT NULL,
                                    -- 冗余自 experiment
            entity_id               VARCHAR(100) NOT NULL,
            -- 事件类型
            event_type              VARCHAR(30) NOT NULL
                                    CHECK (event_type IN (
                                        'exposure',      -- arm 参数生效
                                        'conversion',    -- 达成主指标
                                        'revenue',       -- 产生营收
                                        'metric_value',  -- 自定义连续指标
                                        'error'          -- arm 执行出错（影响数据质量）
                                    )),
            -- 事件数据
            revenue_fen             BIGINT,
                                    -- revenue 事件或 conversion 事件附带的金额
            numeric_value           NUMERIC(15,4),
                                    -- metric_value 事件（如 margin_pct=0.22）
            metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- 附加上下文（store_id, order_id, request_id ...）
            -- 事件时间
            event_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                    -- 业务时间（可能晚于 created_at 到达）
            -- 幂等（防止 retry 导致重复计数）
            idempotency_key         VARCHAR(128),
            -- append-only：不软删不更新
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 幂等：同 entity + event_type + idempotency_key 只一条
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ab_events_idempotency
            ON ab_experiment_events (experiment_id, entity_id, event_type, idempotency_key)
            WHERE idempotency_key IS NOT NULL
    """)
    # 实验 stats 计算：按 (experiment, arm, event_type, event_at) 扫
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_events_experiment_arm_type_time
            ON ab_experiment_events (experiment_id, arm_id, event_type, event_at DESC)
    """)
    # 按 tenant + 时间（用于物化视图批量刷新）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ab_events_tenant_time
            ON ab_experiment_events (tenant_id, event_at DESC)
    """)

    op.execute("ALTER TABLE ab_experiment_events ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS ab_events_tenant_isolation ON ab_experiment_events;
        CREATE POLICY ab_events_tenant_isolation ON ab_experiment_events
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE ab_experiments IS
            'Sprint G: A/B 实验平台主表，含生命周期 + 熔断器配置';
        COMMENT ON COLUMN ab_experiments.circuit_breaker_threshold IS
            'treatment 主指标劣于 control 超过 threshold 比例触发熔断，默认 20%';
        COMMENT ON COLUMN ab_experiments.assignment_strategy IS
            'deterministic_hash（推荐，稳定）/ rollout_percentage / tenant_ring';
        COMMENT ON TABLE ab_experiment_arms IS
            'Sprint G: 实验下各 arm（control + treatment_*）+ 累计统计';
        COMMENT ON TABLE ab_experiment_assignments IS
            'Sprint G: entity → arm 的稳定分配（UNIQUE 保证幂等）';
        COMMENT ON TABLE ab_experiment_events IS
            'Sprint G: 事件流（append-only），exposure/conversion/revenue/metric_value';
        COMMENT ON COLUMN ab_experiment_events.idempotency_key IS
            '防止业务 retry 导致重复计数；客户端需生成稳定的 key（如 order_id + event_type）';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ab_experiment_events CASCADE")
    op.execute("DROP TABLE IF EXISTS ab_experiment_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS ab_experiment_arms CASCADE")
    op.execute("DROP TABLE IF EXISTS ab_experiments CASCADE")
